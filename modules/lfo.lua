-- LFO: phase-stepped low-frequency oscillator. Subscribes to a clock and
-- advances 1/ticks per tick, so the period scales with clock rate.
-- Period in clock ticks, exposed both directly and via a log-scale setter.

LFO = {}
LFO.__index = LFO

local function _shape(name, p)
  if name == 'triangle' then
    return 1 - 4 * math.abs(p - 0.5)        -- -1..+1..-1
  elseif name == 'sine' then
    return math.sin(2 * math.pi * p)
  elseif name == 'saw' then
    return 2 * p - 1                        -- -1..+1
  elseif name == 'square' then
    return p < 0.5 and 1 or -1
  end
  return 0
end

function LFO.new(o)
  o = o or {}
  local self = setmetatable({}, LFO)
  self.out    = o.out    or 4
  self.shape  = o.shape  or 'triangle'
  self.ticks  = o.ticks  or 4096           -- ticks per cycle
  self.amp    = o.amp    or 5.0
  self.center = o.center or 0.0
  self.phase  = 0
  return self
end

function LFO:tick()
  self.phase = (self.phase + 1 / self.ticks) % 1.0
  output[self.out].volts = self.center + self.amp * _shape(self.shape, self.phase)
end

-- Log-scale period control: ticks = round(2^x).
-- x=0 → 1 tick, x=10 → 1024, x=16 → 65536, x=20 → ~1M ticks.
function LFO:set_log_ticks(x)
  self.ticks = math.max(2, math.floor(2 ^ x + 0.5))
end

function LFO:set_ticks(n)  self.ticks = math.max(2, n) end
function LFO:set_shape(s)  self.shape = s end
function LFO:set_amp(a)    self.amp = a end
function LFO:set_center(c) self.center = c end
function LFO:reset()       self.phase = 0 end
