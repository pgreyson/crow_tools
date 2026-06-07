# Tape layering: dB-rigorous parameter design

How `loop_len` and `erase_strength` together determine the time/dB envelope of
layered material.

## The model

Each pass over the loop, old material is multiplied by `1 − erase_strength`.
After N passes, the original signal is at:

    amplitude_ratio = (1 − e)^N
    dB_below_new    = 20 · log₁₀(1 − e) · N
                    = N · per_pass_dB

This treats `erase_strength` as a linear amplitude multiplier per pass. The
crow descriptor calls it *"opposite of feedback,"* which strongly implies
this — but the whimsicalraps wiki does not formally specify the curve. The
linear model is the strongest defensible reading of the docs; verify with
your ears if precision matters.

## Per-pass attenuation table

| erase | 1−e   | dB/pass |
|-------|-------|---------|
| 0.05  | 0.95  | −0.45   |
| 0.10  | 0.90  | −0.92   |
| 0.20  | 0.80  | −1.94   |
| 0.25  | 0.75  | −2.50   |
| 0.30  | 0.70  | −3.10   |
| 0.40  | 0.60  | −4.44   |
| 0.50  | 0.50  | −6.02   |
| 0.60  | 0.40  | −7.96   |
| 0.70  | 0.30  | −10.46  |
| 0.80  | 0.20  | −13.98  |
| 0.90  | 0.10  | −20.00  |
| 1.00  | 0     | −∞ (overwrite) |

## Half-life

Number of passes until material reaches −6 dB:

    half_life_passes = log(0.5) / log(1 − e)

| erase | half-life (passes) |
|-------|--------------------|
| 0.05  | 13.5  |
| 0.10  | 6.6   |
| 0.25  | 2.4   |
| 0.30  | 1.9   |
| 0.50  | 1.0   |

Half-life in seconds = `half_life_passes · loop_len`.

## Designing for a target

Pick *"material from T seconds ago should be at −X dB."* Solve for `e`:

    passes      = T / loop_len
    per_pass_dB = −X / passes
    e           = 1 − 10^(per_pass_dB / 20)

Or equivalently, given `e` and `T`, solve for the dB:

    X = −20 · log₁₀(1 − e) · T / loop_len

## Audibility thresholds (rough)

| level    | character |
|----------|-----------|
| 0 dB     | new material on top |
| −10 dB   | recent past, clearly audible, feels present |
| −20 dB   | background, clearly there, informs texture |
| −30 dB   | faint, threshold of conscious perception |
| −40 dB   | ghost; usually masked by anything new |
| −60 dB   | vanished into noise floor |

These are content-dependent — sparse material decays into perception faster
than dense material, and the room/monitoring noise floor matters. Treat as
rough.

## Worked configurations

### Target: 1 hour ago at −20 dB ("hour-long memory, still audible")

| loop_len | passes/hour | per-pass dB | erase |
|----------|-------------|-------------|-------|
| 60 s     | 60          | −0.33       | 0.038 |
| 300 s    | 12          | −1.67       | 0.176 |
| 900 s    | 4           | −5.00       | 0.438 |
| 1800 s   | 2           | −10.00      | 0.684 |

### Target: 30 min ago at −10 dB ("recent past feels present")

| loop_len | passes/30min | per-pass dB | erase |
|----------|--------------|-------------|-------|
| 60 s     | 30           | −0.33       | 0.038 |
| 300 s    | 6            | −1.67       | 0.176 |
| 900 s    | 2            | −5.00       | 0.438 |

### Target: 5 min ago at −6 dB ("Frippertronics-tight feedback")

| loop_len | passes/5min | per-pass dB | erase |
|----------|-------------|-------------|-------|
| 30 s     | 10          | −0.6        | 0.067 |
| 60 s     | 5           | −1.2        | 0.129 |
| 150 s    | 2           | −3.0        | 0.293 |
| 300 s    | 1           | −6.0        | 0.499 |

## Choosing loop_len

Both parameters move together. Some constraints to keep in mind:

- **Tape buffer cap.** w/tape's underlying buffer is ~3 h (10800 s). Any
  `loop_len` beyond that doesn't behave as a clean loop — the tape itself
  wraps before crow re-zeros it, so material from the prior wrap leaks in
  at slowly-drifting offset.
- **Re-zero misalignment.** Each `looplen()` boundary fires a sequential
  i2c `timestamp(0)` to each tape, ~1-8 ms apart. So the more re-zeros per
  hour (shorter `loop_len`), the more often the stereo image shifts
  fractionally. Long loops avoid this entirely.
- **Audible loop period.** A short `loop_len` (e.g. 30 s) creates a
  recognisable repeating cycle in the layering — Frippertronics character.
  A long `loop_len` (e.g. 1800 s) feels like one continuous slowly-evolving
  blanket; you don't hear the "loop point."

Rule of thumb: pick `loop_len` based on the *musical character* you want
(repetitive vs continuous), then pick `erase` based on how far back you want
material to remain audible.

## Suggesting a `halflife()` helper

Currently `master.lua` exposes `looplen(s)` and `overdub(a)` separately. A
human-friendlier helper would be:

```lua
function halflife(seconds)
  -- given current loop_len, set overdub so material decays by 6 dB after `seconds`
  local passes = seconds / tp.loop_len
  local per_pass = -6.0 / passes
  local e = 1 - 10 ^ (per_pass / 20)
  tp:set_overdub(math.max(0, math.min(1, e)))
end
```

Or `decay_target(db, seconds)` for the full design rule:

```lua
function decay_target(db, seconds)
  local passes = seconds / tp.loop_len
  local per_pass = -math.abs(db) / passes
  local e = 1 - 10 ^ (per_pass / 20)
  tp:set_overdub(math.max(0, math.min(1, e)))
end
```

Not added yet — say the word and I'll wire them into `programs/master.lua`.
