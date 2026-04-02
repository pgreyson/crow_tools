--- slow_lfos
-- 4 non-repeating LFOs across orders of magnitude
-- output 1: ~1s, output 2: ~10s, output 3: ~100s, output 4: ~1000s
-- prime-based periods ensure the pattern never repeats

local periods = {1.1, 10.7, 97.3, 1031.9}

function init()
    for i = 1, 4 do
        output[i].action = loop{
            to(5, periods[i] / 2, 'linear'),
            to(0, periods[i] / 2, 'linear')
        }
        output[i]()
    end
end
