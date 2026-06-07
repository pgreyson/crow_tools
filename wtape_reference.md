# `ii.wtape` parameter reference

Authoritative sources:
- [`monome/crow/lua/ii/wtape.lua`](https://github.com/monome/crow/blob/main/lua/ii/wtape.lua) — descriptor (canonical command list, types, getters)
- [whimsicalraps/wslash wiki — Tape](https://github.com/whimsicalraps/wslash/wiki/Tape) — semantics narrative

## ii type encodings (crow conventions)

| Type | Meaning |
|---|---|
| `s8`   | signed 8-bit int (–128…127). Used for booleans (0/1) and small integers. |
| `s16V` | signed 16-bit fixed-point in **volts**. Lua exposes a float volt value. Common range ±5 V; some params clamped to 0…1. |
| `s32T` | signed 32-bit **time in seconds**, fixed-point. Lua float seconds; sub-second precision supported (precision floor not formally documented). |

## Command table

For each command: index in the descriptor, args, whether it has a getter, range, and effect.

| # | Command | Args | Get? | Range / sensible | Semantics |
|---|---|---|---|---|---|
| 1 | `record` | `active` `s8` | ✓ | `0` / `1` | Arms the record head. Combine with `play` for record-while-play (standard tape behavior). |
| 2 | `play` | `playback` `s8` | ✓ | `–1`, `0`, `1` | `1` = play forward 1×; `0` = stop; `–1` = flip direction (descriptor: *"–1 will flip playback direction"*). |
| 3 | `reverse` | — | — | — | Toggles playback direction. |
| 4 | `speed` | `num` `s16V`, `deno` `s16V` | ✓ (returns `rate` `s16V`) | floats; `num/deno` ratio; negative = reverse | `speed(3,2)` = 1.5×; `speed(-1,1)` = reverse 1×. **Negative flips direction.** |
| 5 | `freq` | `frequency` `s16V` | ✓ | volts (V/oct); `0` V = unity | 1 V/oct speed control. **Maintains current reverse state** (unlike `speed`). |
| 6 | **`erase_strength`** | `level` `s16V` | ✓ | `0.0` … `1.0` | See dedicated section below. |
| 7 | `monitor_level` | `gain` `s16V` | ✓ | float; `0` = muted, `1` = unity | Dry input → output passthrough. Independent of recording. |
| 8 | `rec_level` | `gain` `s16V` | ✓ | float; `0` = no input recorded, `1` = unity | Level of incoming signal written to tape. With `rec_level=0` and `record=1` you get a pure erase pass. |
| 9 | `echo_mode` | `is_echo` `s8` | ✓ | `0` (default) / `1` | `0` = standard deck: erase head precedes record (what you hear is what's about to be written over). `1` = echo mode: play head precedes erase (you hear the previous lap before it's erased). **`1` is required for tape-echo / dub-loop patches.** |
| 10 | `loop_start` | — | — | — | Marks current playhead position as loop in-point. |
| 11 | `loop_end` | — | — | — | Marks current position as loop out-point **and jumps to start** (descriptor side-effect). |
| 12 | `loop_active` | `state` `s8` | ✓ | `0` / `1` | Enables/disables looping between brace points. |
| 13 | `loop_scale` | `scale` `s8` | ✓ | positive = multiply, negative = divide, **`0` = reset to original** (descriptor) | E.g. `2` → 2× longer brace, `–2` → half. **`0` is a reset sentinel, not a no-op.** |
| 14 | `loop_next` | `direction` `s8` | — | nonzero = step the brace forward/back by one loop length, **`0` = jump to loop start** | Moves the loop *brace* (window), not just the playhead. |
| 15 | `timestamp` | `seconds` `s32T` | ✓ (returns `s32T`) | seconds (float, signed) | Absolute seek to a tape position. Getter returns current playhead position in seconds. |
| 16 | `seek` | `seconds` `s32T` | — | seconds (float, signed) | Relative seek from current playhead. **No getter** — use `timestamp` to read position. |
| 18 | `WARNING_clear_tape` | — | — | — | **Erases the entire tape file on SD. Unrecoverable.** No confirmation. The screaming prefix is the warning. |

(Command ID 17 is skipped in the descriptor — reserved for a Teletype-specific `timestampS` getter that's commented out.)

## `erase_strength` in depth

Descriptor docstring (verbatim): *"Strength of erase head when recording. 0 is overdub, 1 is overwrite. Opposite of feedback."*

- **`0.0` — pure overdub.** Erase head off. New input (at `rec_level`) is *summed* onto tape. Old material persists indefinitely (modulo any natural feedback loss). Equivalent to feedback = 1.
- **`1.0` — pure overwrite.** Erase head fully on. Old material under the record head is wiped before new audio is written. Standard tape-record behavior. Equivalent to feedback = 0.
- **Intermediate values** — continuous "level on the erase head." The descriptor's *"Opposite of feedback"* hint suggests `erase_strength ≈ 1 − feedback_gain`, so `0.5` decays old material by ~½ per lap (Frippertronics-style). The exact dB-per-lap law is **not formally documented** — the linear "1 − feedback" interpretation is the strongest claim the docs support.

### Interaction with `echo_mode`

Orthogonal parameters but musically coupled:

| `echo_mode` | `erase_strength` | Result |
|---|---|---|
| 0 | 1 | Normal tape recorder — wipes then writes; you hear what you just wrote. |
| 0 | < 1 | Overdubbing recorder — old + new mixed on tape. |
| **1** | **< 1** | **Canonical tape-echo / dub-loop.** You hear the previous lap, then it's partially erased, leaving a decaying tail. |
| 1 | 1 | Play the loop once, then overwrite. Rarely useful. |

## Power-on defaults

**Not documented.** I checked:
- The crow ii descriptor — only documents a default for `echo_mode` (= `0`).
- The whimsicalraps wslash wiki Tape page — no defaults table.
- Linked release notes — none stated.

The hardware front-panel pots/toggles override ii at the analog stage anyway, so "default" is partially a question about what the module reports if nothing has been sent — which is not specified by the manufacturer.

**Practical rule: if your script depends on a starting value, set it explicitly in `init()` and don't trust an unset module's response.** `master.lua` does this via `Tapes:apply()`.

## Live readings from this rack

Captured 2026-05-01, tape 1, after `master.lua` has initialized but before user interaction:

```
record=0           (init() set 1; was turned off later)
play=0             (init() set 1; was turned off later)
speed=0.9998       ≈ 1.0 (unity forward)
freq=0             0 V → unity
erase_strength=0.0 (master.lua's default — pure overdub)
monitor_level=0.9998  ≈ 1.0 (unity passthrough)
rec_level=0.9998      ≈ 1.0 (unity record)
echo_mode=0        (firmware default, descriptor-documented)
loop_scale=0       (loop window unset)
timestamp=142.28s  (playhead position; was running at some point)
```

The `~0.9998` for unity values is the fixed-point quantization on `s16V` — full-scale `1.0` rounds to `0x7FFF / 0x8000` ≈ 0.9998. Treat as 1.0.

## Quirks & gotchas

- **`WARNING_clear_tape` is unrecoverable.** Only command with the screaming prefix — that's the convention in monome ii libraries. No confirmation step.
- **`WARNING_clear_tape` blocks the transport for *seconds***, not milliseconds. Erasing the tape file is a multi-second SD I/O operation. If you send `timestamp(0)` / `record(1)` / `play(1)` follow-ups while the clear is still running, the tape can hang in a state where ii getters work but the transport won't engage. Recovery requires a eurorack power-cycle. **Wait at least 30 seconds after each `WARNING_clear_tape` before sending any other transport command** — there's no completion-getter to poll.
- **`loop_scale(0)` is a reset, not a no-op.** Easy to misuse if you bind it to bipolar CV that crosses zero.
- **`loop_next(0)` jumps to loop start.** Sentinel, not null direction.
- **`loop_end` jumps the playhead to loop start** as a side effect — descriptor explicit. Not just a marker change.
- **`speed` flips direction on negative; `freq` preserves direction.** Use `freq` for V/oct without losing reverse state.
- **`seek` has no getter, `timestamp` does.** Read position via `timestamp`.
- **Sub-second `s32T` precision is supported but the floor isn't documented.** In practice well below one frame.
- **Command ID 17 is skipped.** Don't write `cmd=17` in raw ii sends.
