-- Clock: master tick generator. Drives one CV pulse output and
-- fires Lua subscribers, each with its own integer division.
-- Rate can be set directly or driven from a CV input via :map_volts(v).

Clock = {}
Clock.__index = Clock

function Clock.new(o)
  o = o or {}
  local self = setmetatable({}, Clock)
  self.out      = o.out      or 1
  self.rate     = o.rate     or 4.0    -- Hz
  self.pulse_ms = o.pulse_ms or 10
  self.subs     = {}                   -- {{fn, div, count}, ...}
  self.metro    = nil
  return self
end

function Clock:subscribe(fn, div)
  table.insert(self.subs, { fn = fn, div = div or 1, count = 0 })
end

function Clock:start()
  if self.metro then self.metro:stop() end
  self.metro = metro.init{
    event = function() self:_tick() end,
    time  = 1 / self.rate,
    count = -1,
  }
  self.metro:start()
end

function Clock:stop()
  if self.metro then self.metro:stop(); self.metro = nil end
  output[self.out].volts = 0
end

function Clock:set_rate(hz)
  self.rate = math.max(0.01, hz)
  if self.metro then self.metro.time = 1 / self.rate end
end

-- Map -5..+5V to 0.25..32 Hz exponentially (5 octaves around 4 Hz center).
function Clock:map_volts(v)
  self:set_rate(4.0 * 2 ^ (v / 2))
end

function Clock:_tick()
  output[self.out].action = pulse(self.pulse_ms / 1000)
  output[self.out]()
  for _, s in ipairs(self.subs) do
    s.count = s.count + 1
    if s.count >= s.div then
      s.count = 0
      s.fn()
    end
  end
end
