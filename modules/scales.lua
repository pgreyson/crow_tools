-- scales.lua : Scala-style tuning tables. Each scale maps a degree index to a
-- pitch offset in VOLTS (1 V/oct), with a `period` (the repeat interval, in
-- volts) and `count` degrees per period. Octave-repeating scales use period
-- = log2(2) = 1 V; non-octave scales (Bohlen-Pierce) repeat at a different
-- interval (the 3/1 tritave). A sieve pitch value V indexes a scale as
--   degree = V % count ,  register = V // count ,
--   volts  = root + register*period + offs[degree]
-- so the value's wrap around `count` is what makes the melody move without
-- just climbing.
--
-- From druid: scale('bohlen_pierce'); scale_list() prints the names.

Scales = {}
local function log2(x) return math.log(x) / math.log(2) end

Scales.list = {}
local function add(name, period_ratio, offs)
  Scales.list[#Scales.list + 1] =
    { name = name, period = log2(period_ratio), offs = offs, count = #offs }
end

-- n equal divisions of an interval (EDO for 2/1, ED3 for the 3/1 tritave, ...)
local function edo(name, n, period_ratio)
  local p = log2(period_ratio); local o = {}
  for i = 0, n - 1 do o[i + 1] = i * p / n end
  add(name, period_ratio, o)
end

-- just intonation from a ratio list within one period (first ratio should be 1)
local function ji(name, ratios, period_ratio)
  local o = {}
  for i, r in ipairs(ratios) do o[i] = log2(r) end
  add(name, period_ratio, o)
end

edo('chromatic', 12, 2)                                   -- 12-TET (default)
ji ('major_ji', {1, 9/8, 5/4, 4/3, 3/2, 5/3, 15/8}, 2)    -- 5-limit just major
ji ('pentatonic', {1, 9/8, 5/4, 3/2, 5/3}, 2)             -- just major pentatonic
edo('bohlen_pierce', 13, 3)                               -- 13-ED3, non-octave tritave
edo('ed19', 19, 2)                                        -- 19-TET
edo('ed32', 32, 2)                                        -- 32-TET (even 32-tone)
do                                                        -- harmonics 32..63: 32-note JI octave
  local o = {}
  for h = 32, 63 do o[#o + 1] = log2(h / 32) end
  add('harm32', 2, o)
end
do  -- penta_cluster: just pentatonic cores, each wrapped in a 5-microtone
    -- cluster (+/-40, +/-18, 0 cents). Small sieve steps shimmer within a
    -- cluster; larger steps leap between core tones. 25 tones/oct.
  local cores = { 1, 9/8, 5/4, 3/2, 5/3 }
  local det = { -40, -18, 0, 18, 40 }
  local o = {}
  for _, r in ipairs(cores) do
    for _, c in ipairs(det) do o[#o + 1] = log2(r) + c / 1200 end
  end
  add('penta_cluster', 2, o)
end

function Scales.by_name(name)
  for i, s in ipairs(Scales.list) do
    if s.name == name then return s, i end
  end
  return Scales.list[1], 1                                 -- default: chromatic
end

function Scales.get(i) return Scales.list[((i - 1) % #Scales.list) + 1] end

function Scales.names()
  local t = {}
  for i, s in ipairs(Scales.list) do t[i] = s.name .. '(' .. s.count .. ')' end
  return table.concat(t, '  ')
end
