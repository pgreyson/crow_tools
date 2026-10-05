-- Sieve: Xenakis sieve. Membership predicate over an integer step counter;
-- emits pitch (V/oct) on hits and holds a gate HIGH for a pitch-dependent
-- number of clock ticks (monophonic — sieve doesn't advance during the hold).
--
-- Two ways to define membership:
--   residues + combine -- list of {M,I} pairs, combined as 'union' or 'intersection'
--   predicate          -- a Lua function(step) -> bool, full Xenakis power
-- A 'predicate' overrides residues if both are set.
--
-- Note duration model (per hit):
--   N = round(2 ^ (dur_exp * (pitch_volts - pivot)))    clamped >= 1
--   gate stays HIGH for N calls to Sieve:tick()
--   sieve does NOT advance while gate is held
--
-- So:
--   dur_exp = 0        → every note = 1 tick (uniform)
--   dur_exp > 0        → higher pitches last longer
--   dur_exp < 0        → lower pitches last longer
--   pivot              → pitch at which N is always 1 (default mid of pitch range)
--
-- Designed to be driven by an external clock via input[1] mode('change'),
-- but works just as well from an internal metro subscription.

Sieve = {}
Sieve.__index = Sieve

local function _residue_pred(residues, combine)
  combine = combine or 'union'
  return function(n)
    if combine == 'union' then
      for _, r in ipairs(residues) do
        if n % r[1] == r[2] then return true end
      end
      return false
    else  -- intersection
      for _, r in ipairs(residues) do
        if n % r[1] ~= r[2] then return false end
      end
      return #residues > 0
    end
  end
end

function Sieve.new(o)
  o = o or {}
  local self = setmetatable({}, Sieve)
  self.pitch_out = o.pitch_out or 2
  self.gate_out  = o.gate_out  or 3
  self.scale     = o.scale     or {0, 2, 3, 5, 7, 8, 11}   -- semitones in octave
  self.octaves   = o.octaves   or 4                         -- range in octaves
  self.root      = o.root      or 0.0                       -- volts (low end)
  self.invert    = o.invert    or false

  -- Duration model. pivot defaults to the mid of the pitch range so dur_exp
  -- of 0 → uniform 1-tick notes, sign of dur_exp picks high-long vs low-long.
  self.dur_exp = o.dur_exp or 0.0
  self.pivot   = o.pivot   or (self.octaves * 0.5)
  self.hold    = 0   -- ticks remaining on the currently-held gate (0 = idle)
  self.log     = o.log or false     -- opt in via sieve_log(true) from druid

  self.predicate = o.predicate or _residue_pred(o.residues or {{2,0}}, o.combine)
  self.step      = 0
  return self
end

function Sieve:set_dur_exp(v) self.dur_exp = v end
function Sieve:set_pivot(v)   self.pivot = v end

function Sieve:set_residues(residues, combine)
  self.predicate = _residue_pred(residues, combine)
end

function Sieve:set_predicate(fn) self.predicate = fn end
function Sieve:set_scale(s)      self.scale = s end
function Sieve:set_root(v)       self.root = v end
function Sieve:set_octaves(n)
  self.octaves = math.max(1, n)
  self.pivot = self.octaves * 0.5   -- re-center the pivot when range changes
end

function Sieve:_voltage_for(step)
  local total = #self.scale * self.octaves
  local pos   = step % total
  local oct   = math.floor(pos / #self.scale)
  local idx   = pos % #self.scale
  return self.root + oct + self.scale[idx + 1] / 12
end

-- One clock-tick callback. Holds gate for N ticks per hit; sieve pauses
-- advancing while the gate is held (monophonic).
function Sieve:tick()
  if self.hold > 0 then
    self.hold = self.hold - 1
    if self.hold == 0 then
      output[self.gate_out].volts = 0
      if self.log then print('  release') end
    end
    return
  end
  local hit = self.predicate(self.step)
  if self.invert then hit = not hit end
  if hit then
    local v = self:_voltage_for(self.step)
    output[self.pitch_out].volts = v
    local n = math.floor(0.5 + 2 ^ (self.dur_exp * (v - self.pivot)))
    if n < 1 then n = 1 end
    self.hold = n
    output[self.gate_out].volts = 5
    if self.log then
      print(string.format('hit  step=%d  pitch=%.3fV  N=%d  (dur_exp=%.2f)',
                          self.step, v, n, self.dur_exp))
    end
  end
  self.step = self.step + 1
end

function Sieve:reset()
  self.step = 0
  self.hold = 0
  output[self.gate_out].volts = 0
end
