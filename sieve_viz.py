#!/usr/bin/env python3
"""sieve_viz: show the dual-sieve terms as text notation + an SVG/HTML page.

Fetches params from the crow's `dump()` (programs/sieve_dual.lua) and
reconstructs everything else locally: this file mirrors the crow's sampling
BIT-EXACTLY (integer-LCG hash), so moduli/residues/patterns computed here are
identical to what the crow is playing. If you change the sampling in
modules/sieve_terms.lua, change it here too.

  python3 sieve_viz.py                # fetch, print notation, write+open HTML
  python3 sieve_viz.py --text         # terminal notation only
  python3 sieve_viz.py --no-fetch     # render program defaults (no serial)
  python3 sieve_viz.py --html out.html --no-open

Serial rules (CLAUDE.md): context-managed port, timeouts, no SIGKILL.
Close druid first — on macOS it silently consumes the crow's replies.
"""
import argparse, math, subprocess, sys, time

MMAX_DUR, MMAX_PITCH = 96, 48

# ---- bit-exact mirrors of modules/sieve_terms.lua ---------------------------

def hash01(a, b, c):
    n = (a * 8121 + b * 28411 + c * 13849) % 65536
    n = (n * 9301 + 49297) % 65536
    n = (n * 9301 + 49297) % 65536
    return (n + 0.5) / 65536.0

def gauss01(a, b):
    u1 = max(hash01(a, 1, b), 1e-9)
    u2 = hash01(a, 2, b)
    return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)

def mixture(p, seed, mmax):
    """Sampled peaks [(mu,w)...] and the density function f(m) (continuous m)."""
    K = max(1, round(p['n_peaks']))
    sd = math.floor(seed * 1000)
    peaks, ws = [], 0.0
    for k in range(1, K + 1):
        mu = p['center'] * math.exp(gauss01(k, sd) * p['spread'])
        w = hash01(k, 3, sd) ** (1 + 6 * p['dominance'])
        peaks.append([max(2.0, min(mu, mmax)), w]); ws += w
    for pk in peaks:
        pk[1] /= max(ws, 1e-9)
    width = max(0.02, p['width'])
    def f(m):
        return sum(w * math.exp(-((math.log(m) - math.log(mu)) ** 2) / (2 * width * width))
                   for mu, w in peaks)
    return peaks, f

def sample_moduli(p, terms, seed, mmax):
    peaks, f = mixture(p, seed, mmax)
    sd = math.floor(seed * 1000)
    dens = {m: f(m) for m in range(2, mmax + 1)}
    out = []
    for t in range(1, max(1, round(terms)) + 1):
        Z = sum(dens.values())
        if Z < 1e-12: break
        r = hash01(t, 4, sd) * Z
        acc = 0.0
        for m in sorted(dens):
            acc += dens[m]
            if acc >= r:
                out.append(m); del dens[m]; break
    return sorted(out), peaks, f

def draw_residues(M, density, conc, seed):
    M = max(1, round(M))
    density = min(1.0, max(0.0, density)); conc = min(1.0, max(0.0, conc))
    k = conc * 6.0; off = seed - math.floor(seed); T = 2 * math.pi
    w = {r: math.exp(k * math.cos(T * (r / M - off))) for r in range(M)}
    wm = max(w.values())
    res = [r for r in range(M) if hash01(r, M, math.floor(seed * 1000)) < density * w[r] / wm]
    return res or [max(w, key=w.get)]

def residues_for(moduli, density, conc, seed):
    n = len(moduli)
    density = min(1.0, max(0.0, density))
    per = 1 - (1 - density) ** (1 / n) if n > 1 else density
    return {M: draw_residues(M, per, conc, seed) for M in moduli}

# ---- mirror of modules/scales.lua -------------------------------------------

def _log2(x): return math.log(x, 2)

def _edo(n, pr): return [_log2(pr)] and [i * _log2(pr) / n for i in range(n)]

SCALES = {
    'chromatic':     (_edo(12, 2), _log2(2)),
    'major_ji':      ([_log2(r) for r in (1, 9/8, 5/4, 4/3, 3/2, 5/3, 15/8)], _log2(2)),
    'pentatonic':    ([_log2(r) for r in (1, 9/8, 5/4, 3/2, 5/3)], _log2(2)),
    'bohlen_pierce': (_edo(13, 3), _log2(3)),
    'ed19':          (_edo(19, 2), _log2(2)),
    'ed32':          (_edo(32, 2), _log2(2)),
    'harm32':        ([_log2(h / 32) for h in range(32, 64)], _log2(2)),
    'penta_cluster': ([_log2(r) + c / 1200 for r in (1, 9/8, 5/4, 3/2, 5/3)
                       for c in (-40, -18, 0, 18, 40)], _log2(2)),
}

# ---- fetch ------------------------------------------------------------------

def find_port(explicit):
    if explicit: return explicit
    from serial.tools import list_ports
    found = [p.device for p in list_ports.comports() if (p.vid, p.pid) == (0x0483, 0x5740)]
    if len(found) != 1:
        sys.exit(f"need exactly one crow on USB (found {len(found)}); use --port")
    return found[0]

def parse_dump_lines(text_lines):
    """Parse the three DUMP* lines (from serial or a captured print buffer)
    into the state dict; returns None if incomplete."""
    lines = {l.split()[0]: l.split()[1:] for l in text_lines if l.startswith('DUMP')}
    if 'DUMP1' not in lines or 'DUMP3' not in lines:
        return None
    d1 = lines['DUMP1']
    def sieve(v):
        c, sp, k, w, dom, t, den, cc, sd = v
        return dict(center=float(c), spread=float(sp), n_peaks=int(k), width=float(w),
                    dominance=float(dom), terms=int(t), density=float(den),
                    conc=float(cc), seed=float(sd))
    st = dict(rate=float(d1[0]), cycle=float(d1[1]), scale=d1[2], registers=int(d1[3]),
              root=float(d1[4]), gate_ratio=float(d1[5]), span=int(d1[6]),
              pitch_span=int(d1[7]), step=int(d1[8]), pitch_i=int(d1[9]),
              saw=float(d1[10]), dur=sieve(lines['DUMP2']), pitch=sieve(lines['DUMP3']))
    if 'DUMP4' in lines:            # slew sieve (older builds don't emit it)
        d4 = lines['DUMP4']
        st['slew'] = sieve(d4[:9])
        st['slew_span'] = int(d4[9])
        st['slew_min'], st['slew_max'] = float(d4[10]), float(d4[11])
        st['slew_shapes'] = d4[12].split(',') if len(d4) > 12 else ['sine']
    return st

def fetch(port):
    import serial
    deadline = time.time() + 10
    with serial.Serial(port, 115200, timeout=1) as s:
        s.reset_input_buffer()
        s.write(b'dump()\n'); s.flush()
        buf = ''
        while time.time() < deadline and 'DUMP3' not in buf:
            buf += s.read(1000).decode(errors='replace')
    st = parse_dump_lines(buf.splitlines())
    if st is None:
        sys.exit("no reply from crow. Is druid open? (it silently eats replies — quit it and retry)")
    return st

DEFAULTS = dict(rate=2.0, cycle=60.0, scale='chromatic', registers=2, root=0.0,
                gate_ratio=0.6, span=120, pitch_span=64, step=0, pitch_i=1, saw=0.0,
                dur=dict(center=10, spread=0.5, n_peaks=3, width=0.25, dominance=0.5,
                         terms=4, density=0.35, conc=0.0, seed=0.0),
                pitch=dict(center=5, spread=0.5, n_peaks=2, width=0.25, dominance=0.3,
                           terms=3, density=0.5, conc=0.3, seed=0.0))

# ---- derivation -------------------------------------------------------------

def derive(st):
    out = {}
    for name, mmax, span in (('dur', MMAX_DUR, st['span']), ('pitch', MMAX_PITCH, st['pitch_span'])):
        p = st[name]
        moduli, peaks, f = sample_moduli(p, p['terms'], p['seed'], mmax)
        res = residues_for(moduli, p['density'], p['conc'], p['seed'])
        pairs = [(M, I) for M in moduli for I in res[M]]
        members = [n for n in range(span) if any(n % M == I for M, I in pairs)]
        out[name] = dict(moduli=moduli, peaks=peaks, f=f, res=res, pairs=pairs,
                         members=members, mmax=mmax, span=span)
    offs, period = SCALES.get(st['scale'], SCALES['chromatic'])
    cnt = len(offs)
    def volts(v):
        return st['root'] + (v // cnt % max(1, st['registers'])) * period + offs[v % cnt]
    out['volts'] = volts
    out['scale_count'] = cnt
    out['scale_period'] = period
    return out

def notation(st, dv):
    def terms_str(name):
        return ' + '.join(f"{M}@{{{','.join(map(str, dv[name]['res'][M]))}}}"
                          for M in dv[name]['moduli'])
    d, p = dv['dur'], dv['pitch']
    onset = len(d['members']) / max(1, d['span'])
    lines = [
        f"duration: {terms_str('dur')}",
        f"          span={d['span']}  onsets={len(d['members'])} ({onset:.0%})  ~{st['rate']*onset:.2f} notes/s",
        f"pitch:    {terms_str('pitch')}",
        f"          {len(p['members'])} members / span {p['span']} -> {st['scale']}({dv['scale_count']}) x {st['registers']} reg",
        f"rate={st['rate']:.2f} Hz  cycle={st['cycle']:.1f} s  gate={st['gate_ratio']:.2f}  saw={st['saw']:.3f}  step={st['step']}",
    ]
    return '\n'.join(lines)

# ---- SVG --------------------------------------------------------------------

W = 960
FG, DIM, ACC, ACC2, ACC3 = '#d8d4c8', '#4a4a55', '#5fd0b8', '#e0965a', '#b48be0'

def svg_distribution(dv, name, y0):
    d = dv[name]; mmax = d['mmax']
    lx = lambda m: 70 + (math.log(m) - math.log(2)) / (math.log(mmax) - math.log(2)) * (W - 120)
    h, base = 90, y0 + 100
    fmax = max(d['f'](m / 4) for m in range(8, mmax * 4)) or 1
    pts = ' '.join(f"{lx(m/4):.1f},{base - d['f'](m/4)/fmax*h:.1f}" for m in range(8, mmax * 4))
    parts = [f'<text x="70" y="{y0+12}" fill="{FG}" font-size="13">{name} moduli distribution — '
             f'{len(d["peaks"])} peaks sampled (stems) → {len(d["moduli"])} moduli drawn (dots), log axis</text>',
             f'<polyline points="{pts}" fill="none" stroke="{ACC}" stroke-width="1.5" opacity="0.8"/>',
             f'<line x1="70" y1="{base}" x2="{W-50}" y2="{base}" stroke="{DIM}"/>']
    for mu, w in d['peaks']:
        parts.append(f'<line x1="{lx(mu):.1f}" y1="{base}" x2="{lx(mu):.1f}" y2="{base - w*h:.1f}" stroke="{ACC3}" stroke-width="2" opacity="0.7"/>')
    for M in d['moduli']:
        parts.append(f'<circle cx="{lx(M):.1f}" cy="{base}" r="5" fill="{ACC2}"/>'
                     f'<text x="{lx(M):.1f}" y="{base+16}" fill="{ACC2}" font-size="11" text-anchor="middle">{M}</text>')
    for m in (2, 4, 8, 16, 32, 64, mmax):
        parts.append(f'<text x="{lx(m):.1f}" y="{base+30}" fill="{DIM}" font-size="9" text-anchor="middle">{m}</text>')
    return '\n'.join(parts), base + 40

def svg_rings(dv, name, y0):
    d = dv[name]
    parts = [f'<text x="70" y="{y0+12}" fill="{FG}" font-size="13">{name} residues — '
             f'one ring per drawn modulus (terms={len(d["moduli"])}, not n_peaks)</text>']
    cx0, cy, R = 130, y0 + 75, 42
    for i, M in enumerate(d['moduli']):
        cx = cx0 + i * 130
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{R}" fill="none" stroke="{DIM}"/>')
        for r in range(M):
            a = -math.pi / 2 + 2 * math.pi * r / M
            x, y = cx + R * math.cos(a), cy + R * math.sin(a)
            on = r in d['res'][M]
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{4 if on else 1.7}" fill="{ACC2 if on else DIM}"/>')
        parts.append(f'<text x="{cx}" y="{cy + R + 18}" fill="{FG}" font-size="11" text-anchor="middle">'
                     f'{M}@{{{",".join(map(str, d["res"][M]))}}}</text>')
    return '\n'.join(parts), cy + R + 32

def svg_onsets(st, dv, y0):
    d = dv['dur']
    n = min(d['span'], 480)
    sx = lambda i: 70 + i / n * (W - 120)
    base = y0 + 55
    parts = [f'<text x="70" y="{y0+12}" fill="{FG}" font-size="13">onset pattern (first {n} of {d["span"]} slots, gate shaded)</text>',
             f'<line x1="70" y1="{base}" x2="{W-50}" y2="{base}" stroke="{DIM}"/>']
    mem = [m for m in d['members'] if m < n]
    for i, m in enumerate(mem):
        nxt = mem[i + 1] if i + 1 < len(mem) else n
        gate = m + (nxt - m) * st['gate_ratio']
        parts.append(f'<rect x="{sx(m):.1f}" y="{base-14}" width="{max(0.8,(sx(gate)-sx(m))):.1f}" height="14" fill="{ACC}" opacity="0.35"/>')
        parts.append(f'<line x1="{sx(m):.1f}" y1="{base-18}" x2="{sx(m):.1f}" y2="{base}" stroke="{ACC}" stroke-width="1.4"/>')
    if st['step'] < n:
        parts.append(f'<path d="M {sx(st["step"]):.1f} {base+4} l -5 9 l 10 0 z" fill="{ACC2}"/>')
    parts.append(f'<rect x="70" y="{base+18}" width="{(W-120)*st["saw"]:.1f}" height="3" fill="{ACC3}" opacity="0.8"/>'
                 f'<text x="{W-50}" y="{base+24}" fill="{DIM}" font-size="9" text-anchor="end">saw {st["saw"]:.2f}</text>')
    return '\n'.join(parts), base + 36

def svg_gamut(st, dv, y0):
    p = dv['pitch']; volts = dv['volts']
    vs = [volts(v) for v in p['members']]
    vmin, vmax = min(vs), max(vs)
    rng = max(0.2, vmax - vmin)
    sx = lambda i: 70 + i / max(1, len(p['members']) - 1) * (W - 120)
    sy = lambda v: y0 + 130 - (v - vmin) / rng * 100
    parts = [f'<text x="70" y="{y0+12}" fill="{FG}" font-size="13">pitch contour — one pass, {st["scale"]} (y = volts)</text>']
    for reg in range(st['registers'] + 1):
        v = st['root'] + reg * dv['scale_period']
        if vmin - 0.05 <= v <= vmax + 0.05:
            parts.append(f'<line x1="70" y1="{sy(v):.1f}" x2="{W-50}" y2="{sy(v):.1f}" stroke="{DIM}" stroke-dasharray="2,4"/>')
    pts = ' '.join(f"{sx(i):.1f},{sy(v):.1f}" for i, v in enumerate(vs))
    parts.append(f'<polyline points="{pts}" fill="none" stroke="{ACC3}" stroke-width="1" opacity="0.55"/>')
    for i, v in enumerate(vs):
        parts.append(f'<circle cx="{sx(i):.1f}" cy="{sy(v):.1f}" r="3" fill="{ACC3}"/>')
    return '\n'.join(parts), y0 + 150

def render_svg_panels(st, dv):
    """All six panels as one <svg> element string (for embedding elsewhere)."""
    body, y = [], 20
    for fn in (lambda y: svg_distribution(dv, 'dur', y),
               lambda y: svg_rings(dv, 'dur', y),
               lambda y: svg_distribution(dv, 'pitch', y),
               lambda y: svg_rings(dv, 'pitch', y),
               lambda y: svg_onsets(st, dv, y),
               lambda y: svg_gamut(st, dv, y)):
        s, y = fn(y)
        body.append(s)
        y += 14
    return (f'<svg width="{W}" height="{y}" style="background:#16161c;border-radius:8px">'
            + '\n'.join(body) + '</svg>')

def render_html(st, dv, path):
    body, y = [], 20
    for fn in (lambda y: svg_distribution(dv, 'dur', y),
               lambda y: svg_rings(dv, 'dur', y),
               lambda y: svg_distribution(dv, 'pitch', y),
               lambda y: svg_rings(dv, 'pitch', y),
               lambda y: svg_onsets(st, dv, y),
               lambda y: svg_gamut(st, dv, y)):
        s, y = fn(y)
        body.append(s)
        y += 14
    note = notation(st, dv).replace('&', '&amp;').replace('<', '&lt;')
    html = (f'<!doctype html><meta charset="utf-8"><title>sieve terms</title>'
            f'<body style="background:#101014;color:{FG};font-family:Menlo,monospace;margin:24px">'
            f'<pre style="font-size:12px;color:{FG}">{note}</pre>'
            f'<svg width="{W}" height="{y}" style="background:#16161c;border-radius:8px">'
            + '\n'.join(body) + '</svg></body>')
    with open(path, 'w') as f:
        f.write(html)

# ---- main -------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port'); ap.add_argument('--html', default='/tmp/sieve_viz.html')
    ap.add_argument('--text', action='store_true'); ap.add_argument('--no-fetch', action='store_true')
    ap.add_argument('--no-open', action='store_true')
    a = ap.parse_args()
    st = DEFAULTS if a.no_fetch else fetch(find_port(a.port))
    dv = derive(st)
    print(notation(st, dv))
    if not a.text:
        render_html(st, dv, a.html)
        print(f"\nwrote {a.html}")
        if not a.no_open:
            subprocess.run(['open', a.html])

if __name__ == '__main__':
    main()
