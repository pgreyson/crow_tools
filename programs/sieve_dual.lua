-- requires: sieve_terms, scales
-- sieve_dual: two independent Xenakis sieves driving the video rack.
--
--   DURATION sieve -> rhythm. Its member positions over one period partition
--     time; the GAPS between members are the note durations. The gaps always
--     sum to the period (LCM), so we scale them by cycle/LCM to make one pass
--     last exactly `cycle` seconds. Period = a fixed rhythm RESOLUTION
--     (dur_span slots), NOT wall time — so a 24 h cycle needs no huge lists,
--     the cycle just stretches each gap.
--   PITCH sieve -> melody. Its member VALUES index a selectable Scala scale:
--     degree = value % count, register = value // count. The wrap around the
--     scale size is what makes the line move instead of just climbing.
--   SLEW sieve -> glide. Per note, its member value sets the slew-function
--     parameters on out 1: time (as a RATIO of that note's duration, so it
--     scales with rate/cycle — 0 = snap, 1 = the whole note is one morph)
--     and shape (value indexes slew_shapes; one entry = fixed shape).
--
-- Controlled by CV from the rack; outputs feed OWL -> bridge -> OBS shaders.
-- clock.run only (dt can exceed metro's ~18 s cap). init() stages; call start().
--
--   in 1  : rate   CV  -> ABSOLUTE event density (ticks/sec, exp 0.05..100 Hz;
--                         notes/sec ~= rate * dur.density, cycle-independent)
--   in 2  : glide  CV  -> ONE knob, BOTH slew params. Sets the RANGE the slew
--                         sieve plays within: -5 V = min/max 0 (stepped),
--                         0 V = 0..1 (sieve's full choice), +5 V = 1..2
--                         (all notes morph, long glides overlap/retarget).
--                         Also centers the shape palette (snappy->smooth);
--                         each note's sieve value jitters +-1 around it.
--                         (cycle moved to druid: cycle_s(secs), default 600)
--   out 1 : pitch (V/oct, quantized to the current scale)
--   out 2 : gate  (per note, gate_ratio of the duration)
--   out 3 : slow -5/+5 sawtooth, period = cycle length
--   out 4 : free
--
-- Scale + sieve-shape params are druid setters (see bottom).

local S = {
  cycle   = 600.0,      -- s, wall-clock length of one full pass (druid cycle_s)
  -- Moduli are SAMPLED from a hierarchical distribution (sample_moduli):
  -- K peak centers drawn from a lognormal landscape (center, spread), each
  -- with a drawn weight (`dominance` skews toward one-big-peak-plus-little-
  -- ones), Gaussian peak width `width` (a log ratio); `terms` moduli drawn
  -- from the resulting mixture. `seed` re-rolls the whole cascade.
  dur   = { center = 10, spread = 0.5, n_peaks = 3, width = 0.25,
            dominance = 0.5, terms = 4, density = 0.35, conc = 0.0, seed = 0.0 },
  pitch = { center = 5,  spread = 0.5, n_peaks = 2, width = 0.25,
            dominance = 0.3, terms = 3, density = 0.5, conc = 0.3, seed = 0.0 },
  slew  = { center = 7,  spread = 0.5, n_peaks = 2, width = 0.25,
            dominance = 0.4, terms = 3, density = 0.5, conc = 0.0, seed = 0.0 },
  rate = 2.0,           -- ticks/sec — ABSOLUTE density (from in1 CV): notes/sec
                        -- ~= rate * dur.density, independent of cycle length
  pitch_span = 64,      -- pitch sieve period; > scale count so values wrap
  registers = 2,        -- how many scale periods (octaves) the melody spans
  root = 0.0,
  gate_ratio = 0.6,
  slew_span = 48,       -- slew sieve period; values normalize over it
  slew_min = 0.0,       -- glide-time ratio of note duration at value 0
  slew_max = 1.0,       -- ... at value slew_span-1
  slew_shapes = { 'logarithmic', 'linear', 'sine' },
                        -- ORDERED palette, snappy -> smooth: glide CV centers
                        -- it, per-note sieve value jitters +-1 around that
  glide_u = 0.5,        -- in2 glide CV, normalized (0.5 = legacy 0..1 range)
}

-- runtime -------------------------------------------------------------------
local dur_pairs, dur_moduli = {}, {}
local dur_span = 16       -- rhythm slots per cycle = rate * cycle (streamed)
local dur_step = 0
local gate_hold = 0
local pitch_seq, pitch_moduli = { 0 }, {}
local pitch_i = 1
local pitch_str = 1   -- golden-stride through the members: non-monotonic walk
local slew_seq, slew_moduli = { 0 }, {}
local slew_i = 1
local slew_str = 1

local function gcd(a, b)
  while b ~= 0 do a, b = b, a % b end
  return a
end
local scale_def = Scales.by_name('chromatic')
local saw_phase = 0.0
local main_id, saw_id = nil, nil
local running = false
local last_span = nil

-- CV maps --------------------------------------------------------------------
local function clamp01(u) return math.max(0.0, math.min(1.0, u)) end
-- Rate ceiling 16 Hz: 100 Hz of Lua clock wakeups + input streams overflowed
-- the crow event queue (REPL dead until power-cycle, 2026-08-14). "Discrete
-- noise" via raw tick rate is out of reach from Lua — accept the floor.
local function map_rate(v) return 0.05 * (16.0 / 0.05) ^ clamp01((v + 5) / 10) end

-- sieve -> member positions over [0, period) --------------------------------
local function members_of(pairs_, period)
  local m = {}
  for n = 0, period - 1 do
    for _, p in ipairs(pairs_) do
      if n % p[1] == p[2] then m[#m + 1] = n; break end
    end
  end
  return m
end

-- Duration sieve is STREAMED, never enumerated: membership is tested per
-- tick, so the span (= rate * cycle slots) can be millions with constant
-- memory. Density is ABSOLUTE: the tick clock runs at S.rate regardless of
-- cycle length — long cycle + dense is a valid combination.
local function dhit(n)
  for _, p in ipairs(dur_pairs) do
    if n % p[1] == p[2] then return true end
  end
  return false
end

-- distance to the next member after `from` (capped scan; exact gate length)
local function next_gap(from)
  local cap = math.min(dur_span, 512)
  for g = 1, cap do
    if dhit((from + g) % dur_span) then return g end
  end
  return cap
end

local function respan()
  dur_span = math.max(16, math.floor(S.rate * S.cycle + 0.5))
  dur_step = 0
  gate_hold = 0
  saw_phase = 0.0
  output[2].volts = 0
  last_span = dur_span
end

local function rebuild_duration()
  dur_moduli = SieveTerms.sample_moduli(S.dur, S.dur.terms, S.dur.seed, 96)
  dur_pairs = SieveTerms.residues_for(dur_moduli, S.dur.density, S.dur.conc, S.dur.seed)
  respan()
end

-- Settle-based realign: tempo (S.rate) always applies IMMEDIATELY via the
-- chunked sleep in the main loop; the pattern reset (respan) fires only
-- after the target span has been stable for ~1 s of stream samples.
-- Without this, rapid knob moves respan every 0.2 s sample and the pattern
-- never gets past its first slots (reset storm).
local pending_span, settle = nil, 0
local function maybe_respan()
  local n = math.max(16, math.floor(S.rate * S.cycle + 0.5))
  if last_span ~= nil and math.abs(math.log(n / last_span)) <= 0.05 then
    pending_span, settle = nil, 0                 -- back near current: no-op
    return
  end
  if pending_span ~= nil and math.abs(math.log(n / pending_span)) <= 0.05 then
    settle = settle + 1
    if settle >= 6 then                           -- ~1.2 s stable at 5 Hz
      pending_span, settle = nil, 0
      respan()
    end
  else
    pending_span, settle = n, 1                   -- still moving: retarget
  end
end

-- Shared build for the per-note walked sieves (pitch, slew): sample moduli,
-- enumerate members over the span, derive a golden-ratio stride coprime to
-- the count (walking members in order is a monotonic ramp; the stride
-- visits every member once per cycle in scrambled order instead).
local function build_walk(p, span, mmax)
  local moduli = SieveTerms.sample_moduli(p, p.terms, p.seed, mmax)
  local pairs_ = SieveTerms.residues_for(moduli, p.density, p.conc, p.seed)
  local seq = members_of(pairs_, span)
  if #seq == 0 then seq = { 0 } end
  local m = #seq
  local str = math.max(1, math.floor(m * 0.618 + 0.5))
  while m > 1 and gcd(str, m) ~= 1 do str = str + 1 end
  return seq, str, moduli
end

local function rebuild_pitch()
  pitch_seq, pitch_str, pitch_moduli = build_walk(S.pitch, S.pitch_span, 48)
  pitch_i = 1
end

local function rebuild_slew()
  slew_seq, slew_str, slew_moduli = build_walk(S.slew, S.slew_span, 48)
  slew_i = 1
end

-- pitch value -> volts through the current scale -----------------------------
local function pitch_volts(v)
  local c = scale_def.count
  local deg = v % c
  local reg = math.floor(v / c) % math.max(1, S.registers)
  return S.root + reg * scale_def.period + scale_def.offs[deg + 1]
end

-- ============ control (druid) ==============================================
function speed_v(v) S.rate = map_rate(v); maybe_respan() end   -- in1 sim
-- in2: ONE knob -> BOTH slew params. Time: 0..0.5 raises the ceiling
-- (max 0->1), 0.5..1 raises the floor too (min 0->1, max 1->2) — stepped ->
-- sieve's choice -> all-morph. Shape: glide_u centers the palette (see hit
-- branch). While the CV streams, it owns slew_min/max (slew_range is only
-- a manual override between samples).
function glide_v(v)
  local u = clamp01((v + 5) / 10)
  S.glide_u = u
  S.slew_max = 2.0 * u
  S.slew_min = math.max(0.0, 2.0 * u - 1.0)
end
function rate_hz(hz) S.rate = math.max(0.01, math.min(16.0, hz)); respan() end
function cycle_s(s)  S.cycle = math.max(0.02, s); respan() end

function scale(name)
  scale_def = Scales.by_name(name)
  print('scale: ' .. scale_def.name .. ' (' .. scale_def.count .. ' tones)')
end
function scale_list() print(Scales.names()) end

-- Distribution params, generic setters (saves crow heap over 20 functions):
--   dset('center', 12)  dset('spread', .5)  dset('n_peaks', 3)  dset('width', .3)
--   dset('dominance', .7)  dset('terms', 4)  dset('conc', 0)  dset('seed', .2)
--   pset(...) same keys for the pitch sieve, plus pset('density', .5)
function dset(k, v) S.dur[k] = v; rebuild_duration() end
function pset(k, v) S.pitch[k] = v; rebuild_pitch() end
function sset(k, v) S.slew[k] = v; rebuild_slew() end
function pitch_span(n) S.pitch_span = math.max(4, math.floor(n)); rebuild_pitch() end
function registers(n) S.registers = math.max(1, math.floor(n)) end
function root(v)      S.root = v end
function gate_ratio(r) S.gate_ratio = math.max(0.05, math.min(1.0, r)) end
function slew_span(n) S.slew_span = math.max(4, math.floor(n)); rebuild_slew() end
-- glide-time range as ratios of the note duration (0 = snap; >1 = glides
-- that outlast their note and get retargeted mid-flight — legato smear)
function slew_range(lo, hi)
  S.slew_min = math.max(0.0, lo)
  S.slew_max = math.max(S.slew_min, hi or S.slew_min)
end
-- ORDERED snappy -> smooth (glide CV sweeps through it), e.g.
-- slew_shapes('logarithmic','linear','sine'); one entry = fixed shape
function slew_shapes(...)
  local t = { ... }
  if #t > 0 then S.slew_shapes = t end
  print('shapes: ' .. table.concat(S.slew_shapes, ','))
end

function start()
  stop()
  rebuild_duration()
  rebuild_pitch()
  rebuild_slew()
  running = true
  input[1].mode('stream', 0.2); input[1].stream = function(v) speed_v(v) end
  input[2].mode('stream', 0.2); input[2].stream = function(v) glide_v(v) end

  main_id = clock.run(function()
    while running do
      -- chunked adaptive sleep: re-reads S.rate every <=0.3 s, so a rate
      -- change takes effect mid-tick instead of after a stale long sleep
      local slept = 0.0
      while running do
        local dt = 1.0 / S.rate
        if slept >= dt then break end
        local chunk = math.min(0.3, dt - slept)
        clock.sleep(chunk)
        slept = slept + chunk
      end
      if gate_hold > 0 then
        gate_hold = gate_hold - 1
        if gate_hold == 0 then output[2].volts = 0 end
      end
      if dhit(dur_step) then
        pitch_i = (pitch_i - 1 + pitch_str) % #pitch_seq + 1
        local gap = next_gap(dur_step)
        -- slew sieve: this note's member value sets the glide parameters.
        -- Time is a ratio of the note's own duration (gap / rate seconds),
        -- shape indexes the slew_shapes list. Set both BEFORE volts.
        slew_i = (slew_i - 1 + slew_str) % #slew_seq + 1
        local sv = slew_seq[slew_i]
        local u = sv / math.max(1, S.slew_span - 1)
        -- shape: glide CV centers the ordered palette, sieve jitters +-1
        local np = #S.slew_shapes
        local ci = math.floor(S.glide_u * (np - 1) + 0.5) + (sv % 3) - 1
        if ci < 0 then ci = 0 elseif ci > np - 1 then ci = np - 1 end
        output[1].shape = S.slew_shapes[ci + 1]
        output[1].slew = (S.slew_min + (S.slew_max - S.slew_min) * u)
                         * gap / S.rate
        output[1].volts = pitch_volts(pitch_seq[pitch_i])
        output[2].volts = 5
        gate_hold = math.max(1, math.floor(gap * S.gate_ratio + 0.5))
        if gate_hold >= gap and gap > 1 then gate_hold = gap - 1 end
      end
      dur_step = (dur_step + 1) % dur_span
    end
  end)

  saw_id = clock.run(function()
    while running do
      local sdt = math.max(0.02, math.min(5.0, S.cycle / 500.0))
      clock.sleep(sdt)
      saw_phase = (saw_phase + sdt / S.cycle) % 1.0
      output[3].volts = -5.0 + 10.0 * saw_phase
    end
  end)
  print('sieve_dual: running  scale=' .. scale_def.name)
end

function stop()
  running = false
  if main_id then clock.cancel(main_id); main_id = nil end
  if saw_id  then clock.cancel(saw_id);  saw_id  = nil end
  input[1].mode('none'); input[2].mode('none')
  output[1].slew = 0   -- else the volts=0 below would glide
  for o = 1, 4 do output[o].volts = 0 end
end

-- Machine-parsable state for sieve_viz.py (which mirrors the sampling
-- bit-exactly, so params + position are all the host needs).
function dump()
  local d, p = S.dur, S.pitch
  print(string.format('DUMP1 %.4f %.2f %s %d %.3f %.2f %d %d %d %d %.4f',
    S.rate, S.cycle, scale_def.name, S.registers, S.root, S.gate_ratio,
    dur_span, S.pitch_span, dur_step, pitch_i, saw_phase))
  print(string.format('DUMP2 %.3f %.3f %d %.3f %.3f %d %.3f %.3f %.4f',
    d.center, d.spread, d.n_peaks, d.width, d.dominance, d.terms, d.density, d.conc, d.seed))
  print(string.format('DUMP3 %.3f %.3f %d %.3f %.3f %d %.3f %.3f %.4f',
    p.center, p.spread, p.n_peaks, p.width, p.dominance, p.terms, p.density, p.conc, p.seed))
  local w = S.slew
  print(string.format('DUMP4 %.3f %.3f %d %.3f %.3f %d %.3f %.3f %.4f %d %.3f %.3f %s',
    w.center, w.spread, w.n_peaks, w.width, w.dominance, w.terms, w.density, w.conc, w.seed,
    S.slew_span, S.slew_min, S.slew_max, table.concat(S.slew_shapes, ',')))
end

function status()
  print(string.format('rate=%.2f Hz  cycle=%.1f s  scale=%s(%d)',
                      S.rate, S.cycle, scale_def.name, scale_def.count))
  print(string.format('dur  : span=%d mod={%s} pairs=%d',
                      dur_span, table.concat(dur_moduli, ','), #dur_pairs))
  print(string.format('pitch: span=%d mod={%s} n=%d reg=%d',
                      S.pitch_span, table.concat(pitch_moduli, ','), #pitch_seq, S.registers))
  print(string.format('slew : span=%d mod={%s} n=%d glide=%.2f ratio=%.2f..%.2f shapes=%s',
                      S.slew_span, table.concat(slew_moduli, ','), #slew_seq,
                      S.glide_u, S.slew_min, S.slew_max, table.concat(S.slew_shapes, ',')))
  print(string.format('pos  : step=%d pitch_i=%d saw=%.3f gate=%.2f',
                      dur_step, pitch_i, saw_phase, S.gate_ratio))
end

function init()
  input[1].mode('none'); input[2].mode('none')
  for o = 1, 4 do output[o].volts = 0 end
  -- auto-start on boot so the rack runs standalone (no host needed).
  -- deliberate exception to the no-auto-start rule: if this script ever
  -- misbehaves at boot, recovery is the i2c-jumper procedure, not a
  -- plain power-cycle. stop() from druid returns it to idle.
  clock.run(function() clock.sleep(1.0); start() end)
  print('sieve_dual: auto-starting in 1s. stop() to idle')
end
