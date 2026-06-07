-- requires: tapes, clock, sieve, lfo
-- master: composed live program. CV stack on outs 1-4, tape stack on i2c.
--
-- On boot: tapes recording continuously (ambient), CV stack STAGED but
-- NOT running. Type cv_on() in druid to start the clock + sieve + tri.
--
-- This is intentional — auto-starting CV in init() risks wedging crow if
-- a runtime issue floods the event queue (recovery requires hardware).

local clk = Clock.new{ out = 1, rate = 2.0, pulse_ms = 20 }
local sv  = Sieve.new{
  pitch_out = 2, gate_out = 3,
  -- four coprime primes union'd: LCM = 46189 steps (~6.4 h @ 2 Hz)
  -- combined with 48 chromatic positions (12 tones x 4 octaves), the full
  -- pitch+gate sequence won't repeat for ~13 days at 2 Hz.
  residues  = {{11,0},{13,5},{17,2},{19,7}}, combine = 'union',
  scale     = {0,1,2,3,4,5,6,7,8,9,10,11},   -- equal temperament, full chromatic
  octaves   = 2, root = 0.0,
}
local tri = LFO.new{ out = 4, shape = 'triangle', ticks = 8192, amp = 5.0 }
-- 8-hour memory: 30 min loop, erase 0.135 → material from 8 h ago at -20 dB
local tp  = Tapes.new{ loop_len = 1800, overdub = 0.135, echo_mode = 0,
                       rec_level = 1.0, mon_level = 1.0 }

local cv_subscribed = false

-- ============== tape =================================================
-- Use clock.run instead of metro for the boundary timer: crow's metro
-- silently caps `time` at ~18s in some firmware paths, which broke long loops.
-- clock.sleep handles arbitrary durations.
local _boundary_co = nil
function looplen(s)
  tp.loop_len = s
  if _boundary_co then clock.cancel(_boundary_co); _boundary_co = nil end
  if s and s > 0 then
    tp:_rezero()
    _boundary_co = clock.run(function()
      while true do
        clock.sleep(s)
        tp:_boundary()
      end
    end)
  end
end
function overdub(a)  tp:set_overdub(a) end
function reclevel(g) tp:set_rec_level(g) end
function monlevel(g) tp:set_mon_level(g) end
function echo(b)     tp:set_echo_mode(b) end

-- decay_target(20, 8*3600) sets overdub so material from 8h ago is at -20 dB,
-- given the current loop_len. Solves: e = 1 - 10^(-X/N/20) where N = T/loop_len.
function decay_target(db, seconds)
  local passes = seconds / tp.loop_len
  local per_pass = -math.abs(db) / passes
  local e = math.max(0, math.min(1, 1 - 10 ^ (per_pass / 20)))
  tp:set_overdub(e)
  print(string.format('decay_target: -%g dB @ %gs with loop_len=%gs -> overdub=%.4f',
                      math.abs(db), seconds, tp.loop_len, e))
end

-- halflife(seconds) is the special case: -6 dB after T seconds.
function halflife(seconds) decay_target(6, seconds) end

-- canned modes
function ambient_mode()
  tp:set_echo_mode(false); tp:set_overdub(1.0); looplen(0)
  print('ambient: continuous capture, full overwrite')
end
function loop_mode(s)
  tp:set_echo_mode(false); tp:set_overdub(0.5); looplen(s or 30)
  print('loop: ' .. (s or 30) .. 's, erase=0.5')
end
function dub_mode(s)
  tp:set_echo_mode(true); tp:set_overdub(0.5); looplen(s or 30)
  print('dub: ' .. (s or 30) .. 's, echo on, erase=0.5')
end
function rec_on()    ii.wtape[1].record(1); ii.wtape[2].record(1); tp.recording = true end
function rec_off()   ii.wtape[1].record(0); ii.wtape[2].record(0); tp.recording = false end
function play_on()   ii.wtape[1].play(1);   ii.wtape[2].play(1)   end
function play_off()  ii.wtape[1].play(0);   ii.wtape[2].play(0)   end
function tape_off()  tp:stop() end

-- ============== cv stack control =====================================
function cv_on()
  if not cv_subscribed then
    clk:subscribe(function() sv:tick()  end, 1)
    clk:subscribe(function() tri:tick() end, 1)
    cv_subscribed = true
  end
  clk:start()
  print('cv on  rate=' .. clk.rate .. 'Hz')
end
function cv_off()
  clk:stop()
  output[2].volts = 0; output[3].volts = 0; output[4].volts = 0
  print('cv off')
end
function cv_in(b)
  if b then
    input[1].mode('stream', 0.5)
    input[1].stream = function(v) clk:map_volts(v) end
    print('cv_in: input 1 -> clock rate (sampled at 2 Hz)')
  else
    input[1].mode('none')
    print('cv_in: input 1 disabled')
  end
end

-- ============== clock ================================================
function rate(hz) clk:set_rate(hz) end
function pw(ms)   clk.pulse_ms = ms end

-- ============== sieve ================================================
function residues(r, c) sv:set_residues(r, c) end
function pred(fn)       sv:set_predicate(fn) end
function scale(s)       sv:set_scale(s) end
function octaves(n)     sv:set_octaves(n) end
function root(v)        sv:set_root(v) end
function invert(b)      sv.invert = b end
function gate_ms(n)     sv.gate_ms = n end
function reset_step()   sv:reset() end

-- ============== triangle =============================================
function tri_shape(s)  tri:set_shape(s) end
function tri_log(x)    tri:set_log_ticks(x) end
function tri_ticks(n)  tri:set_ticks(n) end
function tri_amp(a)    tri:set_amp(a) end
function tri_center(c) tri:set_center(c) end

-- ============== status ===============================================
function status()
  local cv_running = cv_subscribed and clk.metro ~= nil
  print('clock  rate=' .. clk.rate .. 'Hz  pw=' .. clk.pulse_ms .. 'ms  running=' .. tostring(cv_running))
  print('sieve  octaves=' .. sv.octaves .. '  root=' .. sv.root)
  print('tri    shape=' .. tri.shape .. '  ticks=' .. tri.ticks)
  print('tape   loop_len=' .. tp.loop_len .. '  overdub=' .. tp.overdub
        .. '  echo=' .. tp.echo_mode .. '  recording=' .. tostring(tp.recording))
end

-- ============== init =================================================
function init()
  ii.pullup(true)

  -- tape: 30s loop, erase=0.5, echo off (default loop_mode)
  tp:apply()
  ii.wtape[1].record(1); ii.wtape[2].record(1)
  ii.wtape[1].play(1);   ii.wtape[2].play(1)
  tp.recording = true
  looplen(tp.loop_len)   -- starts boundary metro + initial rezero

  input[1].mode('none')
  input[2].mode('none')

  cv_on()   -- safe to auto-start now that pulses use ASL (not clock.run)

  print('master ready: ' .. tp.loop_len .. 's loop, erase=' .. tp.overdub
        .. ', CV running.')
end
