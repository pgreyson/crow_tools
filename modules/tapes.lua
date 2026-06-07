-- Tapes: drives two w/tapes (0x71, 0x72) as one stereo pair.
-- Hard re-syncs both heads to position 0 every loop_len seconds.
-- Set self.on_loop = function(self, n) ... end for boundary callbacks.

Tapes = {}
Tapes.__index = Tapes

function Tapes.new(o)
  o = o or {}
  local self = setmetatable({}, Tapes)
  self.loop_len  = o.loop_len  or 10
  self.overdub   = o.overdub   or 0.0   -- 0 = pure overdub, 1 = full overwrite
  self.rec_level = o.rec_level or 1.0
  self.mon_level = o.mon_level or 1.0
  self.echo_mode = o.echo_mode or 0     -- 0 = erase-then-play, 1 = play-then-erase
  self.recording = false
  self.loop_n    = 0
  self.metro     = nil
  self.on_loop   = nil
  return self
end

function Tapes:_both(cmd, ...)
  ii.wtape[1][cmd](...)
  ii.wtape[2][cmd](...)
end

function Tapes:_rezero()
  ii.wtape[1].timestamp(0)
  ii.wtape[2].timestamp(0)
end

function Tapes:apply()
  self:_both('rec_level',      self.rec_level)
  self:_both('monitor_level',  self.mon_level)
  self:_both('erase_strength', self.overdub)
  self:_both('echo_mode',      self.echo_mode)
end

function Tapes:set_echo_mode(b)
  self.echo_mode = b and 1 or 0
  self:_both('echo_mode', self.echo_mode)
end

function Tapes:start(rec)
  self.recording = rec and true or false
  self.loop_n = 0
  self:apply()
  self:_rezero()
  if self.recording then self:_both('record', 1) end
  self:_both('play', 1)
  if not self.metro then
    self.metro = metro.init{
      event = function() self:_boundary() end,
      time  = self.loop_len,
      count = -1,
    }
  end
  self.metro.time = self.loop_len
  self.metro:start()
end

function Tapes:stop()
  if self.metro then self.metro:stop() end
  self:_both('record', 0)
  self:_both('play', 0)
  self.recording = false
end

function Tapes:_boundary()
  self.loop_n = self.loop_n + 1
  self:_rezero()
  if self.on_loop then self:on_loop(self.loop_n) end
end

function Tapes:set_loop_len(s)
  self.loop_len = s
  if self.metro then self.metro.time = s end
end

function Tapes:set_overdub(a)
  self.overdub = a
  self:_both('erase_strength', a)
end

function Tapes:set_rec_level(g)
  self.rec_level = g
  self:_both('rec_level', g)
end

function Tapes:set_mon_level(g)
  self.mon_level = g
  self:_both('monitor_level', g)
end
