#!/usr/bin/env python3
"""crow_sim: run crow Lua programs locally — no hardware, no serial.

Loads the SAME concatenated source that deploy.py flashes (deploy.build) into
a Lua 5.4 VM (lupa), with a thin shim for the crow API surface our programs
use: output[n].volts, input[n].mode/stream, clock.run/sleep/cancel, print.
A browser UI (http://localhost:8777) gives sliders for every sieve parameter
(calling the program's real druid functions), CV-input sliders for in1/in2,
a time-scale multiplier, live CV traces, and the sieve visualizations from
sieve_viz.py (driven by the program's own dump()).

Faithfulness notes:
  - Stochastic draws are BIT-EXACT vs hardware (integer-LCG hash, all
    intermediates < 2^31 — exact in host int64 and crow int32 alike).
  - Float math is float64 here vs float32 on the crow: last-decimal timing/CV
    differences only; structure and patterns match.
  - Not simulated: ASL (output[n].action), metro (stub), ii. Using them
    raises "not simulated" rather than silently doing nothing.

Usage:  python3 crow_sim.py [program]     (default: sieve_dual)
"""
import argparse, heapq, json, math, subprocess, threading, time, sys, webbrowser

try:
    from lupa import lua54
except ImportError:
    sys.exit("crow_sim needs lupa:  python3 -m pip install --user lupa")

import deploy
import sieve_viz

PORT = 8777

# ---------------- crow API shim + scheduler ----------------------------------

class Sim:
    def __init__(self, program):
        self.lock = threading.RLock()
        self.lua = lua54.LuaRuntime(unpack_returned_tuples=True)
        self.vtime = 0.0
        self.time_scale = 1.0
        self.running = True
        self.console = []            # (vtime, line)
        self.traces = {n: [] for n in (1, 2, 3, 4)}   # ch -> [(vtime, volts)]
        self.in_volts = {1: 0.0, 2: 0.0}
        self.in_stream = {1: None, 2: None}           # (period, lua callback)
        self.in_ver = {1: 0, 2: 0}                    # guards stale feed loops
        self.heap = []               # (wake_vtime, seq, kind, payload)
        self.seq = 0
        self.next_id = 1
        self.cancelled = set()

        self._install_shim()
        _, src = deploy.build(program)
        with self.lock:
            self.lua.execute(src)
            self.call('init')

    # -- shim ------------------------------------------------------------
    def _install_shim(self):
        g = self.lua.globals()
        sim = self

        def lua_print(*args):
            line = '\t'.join(str(a) for a in args)
            sim.console.append((sim.vtime, line))
            del sim.console[:-200]
        g.print = lua_print

        # output[1..4]: record volts writes; .action raises (not simulated)
        self.lua.execute("""
            output = {}
            for i = 1, 4 do
              local t = setmetatable({}, {
                __index = function(_, k)
                  if k == 'volts' then return _sim_get_out(i) end
                  error('output.'..tostring(k)..' not simulated')
                end,
                __newindex = function(_, k, v)
                  if k == 'volts' then _sim_set_out(i, v)
                  elseif k == 'action' then error('ASL not simulated')
                  else error('output.'..tostring(k)..' not simulated') end
                end })
              output[i] = t
            end
            input = {}
            for i = 1, 2 do
              local t = setmetatable({}, {
                __index = function(_, k)
                  if k == 'volts' then return _sim_get_in(i) end
                  if k == 'mode' then return function(m, dt) _sim_in_mode(i, m, dt or 0.1) end end
                  return nil
                end,
                __newindex = function(_, k, v)
                  if k == 'stream' then _sim_in_stream(i, v)
                  elseif k == 'change' then _sim_in_stream(i, v)
                  else error('input.'..tostring(k)..' not simulated') end
                end })
              input[i] = t
            end
            -- coroutines stay entirely Lua-side (lupa can't round-trip
            -- thread objects through Python); Python schedules integer ids.
            _cos, _co_next = {}, 1
            clock = {
              run = function(fn)
                local id = _co_next; _co_next = id + 1
                _cos[id] = coroutine.create(fn)
                _sim_schedule(id, 0)
                return id
              end,
              sleep = function(s) coroutine.yield(s) end,
              cancel = function(id) _cos[id] = nil end,
            }
            function _co_resume(id)
              local co = _cos[id]
              if co == nil then return nil end
              local ok, res = coroutine.resume(co)
              if not ok then
                _cos[id] = nil
                print('LUA ERROR: ' .. tostring(res))
                return nil
              end
              if coroutine.status(co) == 'dead' then _cos[id] = nil; return nil end
              return res
            end
            metro = setmetatable({}, { __index = function()
              error('metro not simulated (use clock.run)') end })
        """)
        g._sim_set_out = lambda ch, v: sim._set_out(int(ch), float(v))
        g._sim_get_out = lambda ch: (sim.traces[int(ch)][-1][1] if sim.traces[int(ch)] else 0.0)
        g._sim_get_in = lambda ch: sim.in_volts[int(ch)]
        g._sim_in_mode = lambda ch, mode, dt: sim._in_mode(int(ch), str(mode), float(dt))
        g._sim_in_stream = lambda ch, fn: sim._in_set_stream(int(ch), fn)
        g._sim_schedule = lambda cid, delay: sim._push(sim.vtime + float(delay), 'coro', int(cid))

    def _in_set_stream(self, ch, fn):
        period = self.in_stream[ch][0] if self.in_stream[ch] else 0.1
        self.in_stream[ch] = (period, fn)

    def _set_out(self, ch, v):
        tr = self.traces[ch]
        tr.append((self.vtime, v))
        del tr[:-2400]

    def _in_mode(self, ch, mode, dt):
        self.in_ver[ch] += 1
        if mode == 'none':
            self.in_stream[ch] = None
            return
        cb = self.in_stream[ch][1] if self.in_stream[ch] else None
        self.in_stream[ch] = (dt, cb)
        self._push(self.vtime + dt, 'input', (ch, self.in_ver[ch]))

    def _push(self, when, kind, payload):
        self.seq += 1
        heapq.heappush(self.heap, (when, self.seq, kind, payload))

    def _dispatch(self, kind, payload):
        if kind == 'coro':
            cid = payload
            try:
                res = self.lua.globals()._co_resume(cid)
            except Exception as e:
                self.console.append((self.vtime, f"resume error: {e}"))
                res = None
            if res is not None:
                try:
                    self._push(self.vtime + max(0.001, float(res)), 'coro', cid)
                except (TypeError, ValueError):
                    pass
        elif kind == 'input':
            ch, ver = payload
            if ver != self.in_ver[ch]:
                return                                   # stale feed loop
            st = self.in_stream.get(ch)
            if st:
                if st[1]:
                    try:
                        st[1](self.in_volts[ch])
                    except Exception as e:
                        self.console.append((self.vtime, f"input cb error: {e}"))
                self._push(self.vtime + st[0], 'input', (ch, ver))

    # -- scheduler (runs in its own thread; wall dt * time_scale = vtime) --
    def loop(self):
        last = time.time()
        while self.running:
            now = time.time()
            self.vtime += (now - last) * self.time_scale
            last = now
            with self.lock:
                while self.heap and self.heap[0][0] <= self.vtime:
                    _, _, kind, payload = heapq.heappop(self.heap)
                    self._dispatch(kind, payload)
            time.sleep(0.005)

    # -- deterministic step mode (tests): advance virtual time, no wall clock
    def advance(self, dv):
        target = self.vtime + dv
        with self.lock:
            while self.heap and self.heap[0][0] <= target:
                when, _, kind, payload = heapq.heappop(self.heap)
                self.vtime = max(self.vtime, when)
                self._dispatch(kind, payload)
            self.vtime = target

    # -- host-side helpers -------------------------------------------------
    def call(self, fn, *args):
        with self.lock:
            f = self.lua.globals()[fn]
            if f is None:
                return f"(no function {fn})"
            try:
                return f(*args)
            except Exception as e:
                self.console.append((self.vtime, f"LUA ERROR in {fn}: {e}"))
                return str(e)

    def dump_state(self):
        """Run the program's dump(), capture its prints, parse via sieve_viz."""
        with self.lock:
            mark = len(self.console)
            self.call('dump')
            lines = [l for _, l in self.console[mark:]]
            del self.console[mark:]
        return sieve_viz.parse_dump_lines(lines)

# ---------------- batch push to hardware -------------------------------------

def push_commands(st):
    """druid command lines reproducing the sim's current param state on the
    crow. rate/cycle are NOT sent — on hardware those come from rack CV."""
    cmds = [f"scale('{st['scale']}')",
            f"registers({st['registers']})",
            f"root({st['root']:.3f})",
            f"gate_ratio({st['gate_ratio']:.2f})",
            f"pitch_span({st['pitch_span']})"]
    for fn, p in (('dset', st['dur']), ('pset', st['pitch'])):
        for k in ('center', 'spread', 'n_peaks', 'width', 'dominance',
                  'terms', 'density', 'conc', 'seed'):
            if k in p:
                v = p[k]
                cmds.append(f"{fn}('{k}', {v:g})")
    return cmds

def push_to_crow(st, port=None):
    """Send the batch over serial (safety rules: context-managed, timeouts,
    single pass, no retry loops). Returns a human-readable report."""
    import serial
    import sieve_viz as sv
    try:
        port = port or sv.find_port(None)
    except SystemExit as e:
        return f"push failed: {e}"
    cmds = push_commands(st)
    try:
        with serial.Serial(port, 115200, timeout=1) as s:
            s.reset_input_buffer()
            s.write(b'print("push_check")\n'); s.flush(); time.sleep(0.5)
            if 'push_check' not in s.read(500).decode(errors='replace'):
                return ("push aborted: crow not answering on " + port +
                        " (druid open? it eats replies)")
            for c in cmds:
                s.write((c + '\n').encode()); s.flush(); time.sleep(0.15)
                s.read(1000)                      # drain echo
        return f"pushed {len(cmds)} commands to {port}:\n  " + "\n  ".join(cmds)
    except serial.SerialException as e:
        return f"push failed: {e}"

# ---------------- HTTP UI ----------------------------------------------------

PAGE = """<!doctype html><meta charset="utf-8"><title>crow_sim</title>
<body style="background:#101014;color:#d8d4c8;font-family:Menlo,monospace;font-size:11px;
             margin:0;padding:10px;height:100vh;box-sizing:border-box;overflow:hidden;
             display:grid;grid-template-columns:460px 1fr;gap:12px">
 <div style="overflow:hidden;display:flex;flex-direction:column">
  <div style="margin-bottom:4px"><b>crow_sim — %PROGRAM%</b>&nbsp;
    <button onclick="cmd('start')">start()</button>
    <button onclick="cmd('stop')">stop()</button>
    <button onclick="fetch('/push',{method:'POST'})" title="send current params to the real crow over serial (batch)">→ crow</button>
    scale <select id="scale" onchange="post('scale',[this.value])">
      <option>chromatic</option><option>major_ji</option><option>pentatonic</option>
      <option>bohlen_pierce</option><option>ed19</option><option>ed32</option>
      <option>harm32</option><option>penta_cluster</option></select>
  </div>
  <div id="sliders" style="display:grid;grid-template-columns:1fr 1fr;gap:0 8px"></div>
  <pre id="console" style="height:76px;overflow-y:auto;background:#16161c;padding:5px;border-radius:6px;margin:6px 0 4px"></pre>
  <pre id="notation" style="background:#16161c;padding:5px;border-radius:6px;margin:0;font-size:10px"></pre>
 </div>
 <div style="display:flex;flex-direction:column;height:calc(100vh - 20px);min-width:0">
  <canvas id="traces" width="900" height="150" style="background:#16161c;border-radius:8px;width:100%;height:150px;flex:none"></canvas>
  <div id="viz" style="flex:1;min-height:0;margin-top:8px"></div>
 </div>
<script>
const S=[ // label, fn, args-prefix, min, max, step, initial
 ['in1 rate CV (V)','cv',[1],-5,5,0.01,0],
 ['in2 cycle CV (V)','cv',[2],-5,5,0.01,0],
 ['time scale','timescale',[],1,60,1,1],
 ['dur center','dset',['center'],2,48,0.5,10],
 ['dur spread','dset',['spread'],0,1.5,0.01,0.5],
 ['dur peaks','dset',['n_peaks'],1,6,1,3],
 ['dur width','dset',['width'],0.02,1,0.01,0.25],
 ['dur dominance','dset',['dominance'],0,1,0.01,0.5],
 ['dur terms','dset',['terms'],1,8,1,4],
 ['dur density','dset',['density'],0,1,0.01,0.35],
 ['dur conc','dset',['conc'],0,1,0.01,0],
 ['dur seed','dset',['seed'],0,1,0.001,0],
 ['pitch center','pset',['center'],2,32,0.5,5],
 ['pitch spread','pset',['spread'],0,1.5,0.01,0.5],
 ['pitch peaks','pset',['n_peaks'],1,6,1,2],
 ['pitch width','pset',['width'],0.02,1,0.01,0.25],
 ['pitch dominance','pset',['dominance'],0,1,0.01,0.3],
 ['pitch terms','pset',['terms'],1,8,1,3],
 ['pitch density','pset',['density'],0,1,0.01,0.5],
 ['pitch conc','pset',['conc'],0,1,0.01,0.3],
 ['pitch seed','pset',['seed'],0,1,0.001,0],
 ['registers','registers',[],1,5,1,2],
 ['root (V)','root',[],-3,3,0.05,0],
 ['gate ratio','gate_ratio',[],0.05,1,0.01,0.6],
 ['pitch span','pitch_span',[],8,256,1,64],
];
const sl=document.getElementById('sliders');
for(const [label,fn,pre,mn,mx,st,init] of S){
  // built via DOM APIs: inline oninput attributes broke on the quotes in
  // string args (e.g. pset('terms', ...)), silently killing those sliders
  const row=document.createElement('div');
  row.style.whiteSpace='nowrap';
  const lab=document.createElement('label');
  lab.textContent=label;
  lab.style.cssText='display:inline-block;width:92px;font-size:10px';
  const inp=document.createElement('input');
  inp.type='range'; inp.min=mn; inp.max=mx; inp.step=st; inp.value=init;
  inp.style.cssText='width:84px;vertical-align:middle';
  const val=document.createElement('span');
  val.textContent=init; val.style.fontSize='10px';
  inp.addEventListener('input',()=>{
    val.textContent=inp.value;
    post(fn, pre.concat([parseFloat(inp.value)]));
  });
  row.append(lab,inp,val);
  sl.appendChild(row);
}
function post(fn,args){fetch('/set',{method:'POST',body:JSON.stringify({fn,args})});}
function cmd(fn){post(fn,[]);}
async function tick(){
  try{
    const st=await (await fetch('/state')).json();
    document.getElementById('console').textContent=st.console.join('\\n');
    document.getElementById('notation').textContent=st.notation||'';
    if(st.svg && st.svg!==window._lastSvg){window._lastSvg=st.svg;document.getElementById('viz').innerHTML=st.svg;}
    drawTraces(st.traces, st.vtime, st.window, st.timescale);
  }catch(e){}
  setTimeout(tick, 400);
}
function drawTraces(tr, vt, win, scale){
  const cv=document.getElementById('traces'), c=cv.getContext('2d');
  c.clearRect(0,0,cv.width,cv.height);
  c.fillStyle='#8a8a95'; c.font='11px Menlo';
  c.fillText('t = '+vt.toFixed(1)+' s (virtual)   ×'+scale+'   window '+win+' s', cv.width-330, 12);
  const t0=vt-win;
  const X=t=>((t-t0)/win)*cv.width;
  const lanes={1:[10,70,'#b48be0'],2:[80,30,'#5fd0b8'],3:[120,60,'#e0965a']};
  c.font='10px Menlo';
  for(const ch of [1,2,3]){
    const [y0,h,col]=lanes[ch]; const pts=tr[ch]||[];
    c.strokeStyle=col; c.fillStyle=col;
    c.fillText(ch==1?'out1 pitch':ch==2?'out2 gate':'out3 saw', 4, y0-2);
    c.beginPath(); let started=false, lastv=0;
    for(const [t,v] of pts){
      const x=X(t), y=y0+h-( (v+5)/10 )*h;
      if(!started){c.moveTo(x,y);started=true;}
      else{c.lineTo(x, y0+h-((lastv+5)/10)*h); c.lineTo(x,y);}  // step plot
      lastv=v;
    }
    if(started){c.lineTo(cv.width, y0+h-((lastv+5)/10)*h);}
    c.stroke();
  }
}
tick();
</script>"""

def serve(sim, program, port, open_browser=True):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    last_svg = {'params': None, 'svg': None, 'notation': ''}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _send(self, body, ctype='text/html'):
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.end_headers()
            self.wfile.write(body.encode())
        def do_GET(self):
            if self.path == '/':
                self._send(PAGE.replace('%PROGRAM%', program))
            elif self.path == '/state':
                win = 30.0
                t0 = sim.vtime - win
                traces = {ch: [(round(t, 3), round(v, 4)) for t, v in tr if t >= t0]
                          for ch, tr in sim.traces.items()}
                st = sim.dump_state()
                svg = None; notation = ''
                if st:
                    key = json.dumps([st['dur'], st['pitch'], st['scale'],
                                      st['registers'], st['span'], st['pitch_span']], sort_keys=True)
                    dv = sieve_viz.derive(st)
                    notation = sieve_viz.notation(st, dv)
                    if key != last_svg['params']:
                        last_svg['params'] = key
                        raw = sieve_viz.render_svg_panels(st, dv)
                        # scale to fit the viewport pane: fixed size -> viewBox
                        import re as _re
                        raw = _re.sub(
                            r'<svg width="(\d+)" height="(\d+)" style="([^"]*)"',
                            r'<svg viewBox="0 0 \1 \2" preserveAspectRatio="xMidYMin meet" '
                            r'style="\3;width:100%;height:100%;display:block"',
                            raw, count=1)
                        last_svg['svg'] = raw
                svg = last_svg['svg']          # always send; client diffs
                self._send(json.dumps({
                    'vtime': round(sim.vtime, 3), 'window': win, 'traces': traces,
                    'timescale': sim.time_scale,
                    'console': [l for _, l in sim.console[-12:]],
                    'notation': notation, 'svg': svg}), 'application/json')
        def do_POST(self):
            if self.path == '/push':
                st = sim.dump_state()
                report = push_to_crow(st) if st else "push failed: no dump from program"
                for line in report.splitlines():
                    sim.console.append((sim.vtime, line))
                self._send('ok', 'text/plain')
                return
            n = int(self.headers.get('Content-Length', 0))
            req = json.loads(self.rfile.read(n))
            fn, args = req['fn'], req.get('args', [])
            if fn == 'cv':
                sim.in_volts[int(args[0])] = float(args[1])
            elif fn == 'timescale':
                sim.time_scale = max(1.0, float(args[0]))
            else:
                sim.call(fn, *args)
            self._send('ok', 'text/plain')

    threading.Thread(target=sim.loop, daemon=True).start()
    srv = HTTPServer(('127.0.0.1', port), H)
    print(f"crow_sim: http://127.0.0.1:{port}  (program: {program}; serial never touched)")
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sim.running = False
        print("\ncrow_sim: bye")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('program', nargs='?', default='sieve_dual')
    ap.add_argument('--port', type=int, default=PORT)
    ap.add_argument('--no-open', action='store_true')
    a = ap.parse_args()
    sim = Sim(a.program)
    serve(sim, a.program, a.port, not a.no_open)

if __name__ == '__main__':
    main()
