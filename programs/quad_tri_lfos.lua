-- requires:
--- quad_tri_lfos
-- 4 free-running triangle LFOs. Standalone: no modules, no clock, no input.
-- Each output is a self-restarting ASL triangle loop, so the slope engine
-- runs them in C -- no Lua metros, no event-queue pressure even at audio-ish
-- rates.
--
-- Periods are GEOMETRICALLY (exponentially) spaced from fast to slow:
--   out 1: T_FAST   -- ~as fast as the crow cleanly slews a triangle
--   out 4: T_SLOW   -- 600 s (10 minute period)
--   out 2, 3: equal-ratio steps in between
--
-- Bipolar +/-AMP, centred at 0, so each LFO drives a shader parameter across
-- its FULL 0..1 range through the OWL-ACDC bridge (-5V -> 0.0, +5V -> 1.0).
-- (A 0..5V unipolar triangle would only cover the upper half, 0.5..1.0.)
--
-- Tunables: edit the three constants and re-flash. ratio is derived so the
-- endpoints always land exactly on T_FAST and T_SLOW for any N.

local N      = 4
local T_FAST = 0.002    -- s, out 1 period (lower = faster; ~practical floor)
local T_SLOW = 600      -- s, out 4 period (10 min)
local AMP    = 5        -- V peak (+/-AMP triangle, centred at 0)

function init()
    local ratio = (T_SLOW / T_FAST) ^ (1 / (N - 1))
    for i = 1, N do
        local period = T_FAST * ratio ^ (i - 1)
        local half   = period / 2
        output[i].action = loop{
            to( AMP, half, 'linear'),
            to(-AMP, half, 'linear'),
        }
        output[i]()
    end
end
