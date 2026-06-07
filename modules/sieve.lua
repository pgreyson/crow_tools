-- Sieve: Xenakis sieve. Membership predicate over an integer step counter;
-- emits pitch (V/oct from a scale lookup) and a gate when the step is in.
--
-- Two ways to define membership:
--   residues + combine -- list of {M,I} pairs, combined as 'union' or 'intersection'
--   predicate          -- a Lua function(step) -> bool, full Xenakis power
-- A 'predicate' overrides residues if both are set.

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
  self.gate_ms   = o.gate_ms   or 30
  self.predicate = o.predicate or _residue_pred(o.residues or {{2,0}}, o.combine)
  self.step      = 0
  return self
end

function Sieve:set_residues(residues, combine)
  self.predicate = _residue_pred(residues, combine)
end

function Sieve:set_predicate(fn) self.predicate = fn end
function Sieve:set_scale(s)      self.scale = s end
function Sieve:set_root(v)       self.root = v end
function Sieve:set_octaves(n)    self.octaves = math.max(1, n) end

function Sieve:_voltage_for(step)
  local total = #self.scale * self.octaves
  local pos   = step % total
  local oct   = math.floor(pos / #self.scale)
  local idx   = pos % #self.scale
  return self.root + oct + self.scale[idx + 1] / 12
end

function Sieve:tick()
  local hit = self.predicate(self.step)
  if self.invert then hit = not hit end
  if hit then
    output[self.pitch_out].volts = self:_voltage_for(self.step)
    output[self.gate_out].action = pulse(self.gate_ms / 1000)
    output[self.gate_out]()
  end
  self.step = self.step + 1
end

function Sieve:reset() self.step = 0 end
