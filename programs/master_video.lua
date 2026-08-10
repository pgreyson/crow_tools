-- requires: sieve, lfo
-- master_video: sieve + slow LFO, both driven by an external clock on input 1.
--
-- Signal layout:
--   in  1 : external clock (rising edges advance sieve + LFO)
--   in  2 : dur_exp CV — direct voltage → exponent (0V = uniform 1-tick notes,
--           positive = high pitches longer, negative = low pitches longer)
--   out 1 : unused (free)
--   out 2 : sieve pitch (V/oct)
--   out 3 : sieve gate — HIGH for N clock ticks per hit, where
--           N = round(2 ^ (dur_exp * (pitch - pivot))), clamped >= 1
--   out 4 : slow triangle LFO (±5V), advances 1/ticks per external clock pulse
--           (so period in seconds = ticks × clock_period_seconds)
--
-- No internal metro — everything happens inside the input[1].change callback,
-- or (video rack, no free clock module) an opt-in internal clock via
-- clock.run. Per the crow safety notes, init() sets up state only; opt in
-- via druid:
--   clock_in(true)    -- enable input 1 → sieve + LFO clock (external clock)
--   self_clock(2)     -- OR: internal clock at 2 Hz (self_clock() to stop;
--                        clock.run+clock.sleep, NOT metro — metro caps ~18 s)
--   scale_cv(true)    -- enable input 2 → dur_exp
--   sieve_log(true)   -- optional, print hit/release events

local sv  = Sieve.new{
  pitch_out = 2, gate_out = 3,
  residues  = {{11,0},{13,5},{17,2},{19,7}}, combine = 'union',
  scale     = {0,1,2,3,4,5,6,7,8,9,10,11},
  octaves   = 2, root = 0.0,
  dur_exp   = 0.0,
}
local tri = LFO.new{ out = 4, shape = 'triangle', ticks = 8192, amp = 5.0 }
local sc_id = nil   -- self_clock coroutine handle

-- Input 1: external clock. Each rising edge advances sieve + LFO.
function clock_in(b)
  if b then
    input[1].mode('change', 1.0, 0.1, 'rising')
    input[1].change = function(_)
      sv:tick()
      tri:tick()
    end
    print('clock_in: input 1 -> sieve + triangle (rising edges)')
  else
    input[1].mode('none')
    print('clock_in: input 1 disabled')
  end
end

-- Internal clock (video rack has no spare clock module): self_clock(hz)
-- starts a clock.run loop ticking sieve + triangle; self_clock() stops it.
-- clock.run + clock.sleep, NOT metro — metro.init silently caps ~18 s
-- (CLAUDE.md quirk), and slow meditative rates are exactly the use case.
function self_clock(hz)
  if sc_id then
    clock.cancel(sc_id)
    sc_id = nil
  end
  if hz and hz > 0 then
    local period = 1.0 / hz
    sc_id = clock.run(function()
      while true do
        clock.sleep(period)
        sv:tick()
        tri:tick()
      end
    end)
    print(string.format('self_clock: %.3f Hz -> sieve + triangle', hz))
  else
    print('self_clock: off')
  end
end

-- Input 2: live duration exponent (dur_exp). Direct voltage mapping —
-- 1V CV = exponent of 1.0. 0V = exponent 0 (uniform 1-tick notes).
function scale_cv(b)
  if b then
    input[2].mode('stream', 0.5)
    input[2].stream = function(v) sv:set_dur_exp(v) end
    print('scale_cv: input 2 -> sieve duration exponent (2 Hz sampling)')
  else
    input[2].mode('none')
    sv:set_dur_exp(0)
    print('scale_cv: input 2 disabled, dur_exp reset to 0')
  end
end

-- ============== sieve params (via druid) ==============================
function residues(r, c) sv:set_residues(r, c) end
function pred(fn)       sv:set_predicate(fn) end
function scale(s)       sv:set_scale(s) end
function octaves(n)     sv:set_octaves(n) end
function root(v)        sv:set_root(v) end
function invert(b)      sv.invert = b end
function dur_exp(v)     sv:set_dur_exp(v) end
function pivot(v)       sv:set_pivot(v) end
function reset_step()   sv:reset() end
function sieve_log(b)   sv.log = b end

-- ============== triangle params =======================================
function tri_shape(s)  tri:set_shape(s) end
function tri_log(x)    tri:set_log_ticks(x) end
function tri_ticks(n)  tri:set_ticks(n) end
function tri_amp(a)    tri:set_amp(a) end
function tri_center(c) tri:set_center(c) end
function tri_reset()   tri:reset() end

-- ============== status ===============================================
function status()
  print(string.format('sieve  oct=%d  root=%.2f  dur_exp=%.2f  pivot=%.2f  hold=%d  step=%d',
                      sv.octaves, sv.root, sv.dur_exp, sv.pivot, sv.hold, sv.step))
  print(string.format('tri    shape=%s  ticks=%d  phase=%.3f',
                      tri.shape, tri.ticks, tri.phase))
  print(string.format('in1=%.2fV  in2=%.2fV', input[1].volts, input[2].volts))
end

-- ============== init =================================================
function init()
  input[1].mode('none')
  input[2].mode('none')
  output[1].volts = 0   -- out 1 is unused; pin it low
  print('master_video: idle. Type clock_in(true); scale_cv(true)')
end
