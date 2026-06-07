-- CV: emits control voltage on one of crow's 4 outputs.
-- Modes:
--   'lfo'      -- shaped LFO via crow ASL; rate in Hz, amp in volts
--   'sequence' -- step through self.steps (semitones), one per self.rate seconds
--   'random'   -- new random voltage every self.rate seconds, 0..self.amp + center

CV = {}
CV.__index = CV

function CV.new(o)
  o = o or {}
  local self = setmetatable({}, CV)
  self.out    = o.out    or 1
  self.mode   = o.mode   or 'sequence'
  self.rate   = o.rate   or 0.5
  self.amp    = o.amp    or 5.0
  self.center = o.center or 0.0
  self.steps  = o.steps  or {0, 3, 5, 7, 10, 7, 5, 3}
  self.metro  = nil
  self.idx    = 1
  return self
end

function CV:start()
  self:stop()
  if self.mode == 'lfo' then
    output[self.out].action = lfo(1 / self.rate, self.amp)
    output[self.out]()
  elseif self.mode == 'sequence' then
    self.idx = 1
    self.metro = metro.init{
      event = function()
        output[self.out].volts = self.steps[self.idx] / 12 + self.center
        self.idx = (self.idx % #self.steps) + 1
      end,
      time = self.rate, count = -1,
    }
    self.metro:start()
  elseif self.mode == 'random' then
    self.metro = metro.init{
      event = function()
        output[self.out].volts = math.random() * self.amp + self.center
      end,
      time = self.rate, count = -1,
    }
    self.metro:start()
  end
end

function CV:stop()
  if self.metro then self.metro:stop(); self.metro = nil end
  output[self.out].action = nil
  output[self.out].volts = 0
end

function CV:set_rate(r)
  self.rate = r
  if self.metro then self.metro.time = r end
  if self.mode == 'lfo' then
    output[self.out].action = lfo(1 / r, self.amp)
    output[self.out]()
  end
end

function CV:set_steps(s) self.steps = s; self.idx = 1 end

function CV:trigger(n, ms)
  output[n or self.out].volts = 5
  clock.run(function()
    clock.sleep((ms or 20) / 1000)
    output[n or self.out].volts = 0
  end)
end
