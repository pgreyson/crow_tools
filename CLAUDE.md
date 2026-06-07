# crow_tools — Claude operational notes

General tooling for monome **crow**: reusable Lua modules (`modules/`),
composed programs (`programs/`), and a build/deploy pipeline. crow speaks
USB-CDC serial. Mistakes here have crashed the user's hard drives.
**Read this before touching the bus.**

## One build, multiple racks

The combined program (`master.lua`) bundles every subsystem: stereo w/tape
looper + clock + Xenakis sieve + slow LFO. The **same build runs on every
rack's crow** — there's no per-rack variant.

- **wtape rack**: crow + two w/tape over i2c. Tape + CV stack both active.
- **video rack**: crow only, no w/tape, no i2c. The tape subsystem is inert
  — `ii.wtape` writes are fire-and-forget, so with nothing on the bus they
  just go nowhere. The sieve + slow-LFO CV stack runs identically. No code
  change needed; tape status in `status()` is meaningless there but harmless.

Flash a specific crow with `deploy.py --port`; with no flag it uses the
wtape rack's `DEFAULT_PORT` if present, else auto-detects a crow by VID:PID
(`0483:5740`). Slim per-rack builds are still possible via a program's
`-- requires:` line if flash size or the inert tape activity ever matter.

## Hard rules — USB serial safety

- **NEVER `kill -9` a pyserial process.** SIGKILL skips Python's cleanup,
  leaves the file descriptor orphaned in the kernel, and macOS responds
  with a USB controller reset that **unmounts every drive on the same
  controller**. This has happened twice. Use SIGTERM (default `kill`) so
  Python catches it and runs cleanup.
- **Always use `with serial.Serial(...) as s:`** so the port closes on any
  exception path. No exceptions to this rule.
- **Always set `timeout=N` on the constructor**, and a hard wall-clock
  budget on the script as a whole. Hung reads → stuck process → SIGKILL
  temptation → bus reset.
- **Probes are not free.** Each `python3 -c '... serial.Serial ...'` is a
  potential bus event. Prefer asking the user to type commands in druid
  themselves (zero risk, identical functionality) when there's no good
  reason to do it from this side.
- If the user reports drives went offline after a probe, the recovery is
  `diskutil mount /dev/diskNsM` for each affected partition. macOS treats
  ungracefully-disconnected non-APFS volumes as needing manual remount.

## crow firmware quirks (v4.0.5)

- **`metro.init{ time = N }` silently caps `N` at ~18 seconds.** Use
  `clock.run(function() while true do clock.sleep(N); ... end end)` for
  any boundary timer longer than ~15 s. The status/getter readback lies —
  it will report the value you set even though the metro doesn't honor it.
- **`WARNING_clear_tape` is multi-second blocking SD I/O.** Wait ≥30 s
  after each clear before sending `record(1)`/`play(1)`/`timestamp(0)` or
  the transport hangs. Recovery from a hang requires power-cycling the
  eurorack case (NOT crow USB).
- **Event-queue overflow ("event queue full!" spam) is a recovery
  nightmare.** The bad script reloads from flash on every boot, so simple
  USB power-cycling doesn't fix it. The reliable fix is the i2c jumper
  hardware procedure (bridge centre i2c pin to ground at boot, see
  README.md). Software-side `^^k` (kill Lua) + `^^c` (clear flash) can
  work but is racy because the spam chokes the host CDC buffer.
- **Don't auto-start the CV stack in `init()`.** If the runtime hangs you
  can't recover without DFU. Have `init()` set up state only; expose
  `cv_on()` / `cv_off()` for explicit control.
- **Avoid global names that shadow ASL primitives:** `loop`, `to`, `held`,
  `times`, `lfo`, `pulse`, `wait`, `here`. (We renamed our tape-loop
  helper to `looplen` for this reason.)

## Tape state recovery cheat sheet

| Symptom | Cause | Fix |
|---|---|---|
| crow REPL silent, `^^v` works | Lua VM stuck or in upload-buffer mode | `^^e` then `^^c` |
| crow REPL silent, `^^v` silent too | Event-queue overflow from running script | `^^k` (kill Lua), then `^^c`. Hardware i2c jumper if those don't land. |
| Tape transport not advancing despite `record=1, play=1` | Recent `WARNING_clear_tape` not finished | Power-cycle eurorack case. Wait ≥30 s after clears in future. |
| Tape repeating at unexpected short interval | Front-panel `loop_active` set on the module | `ii.wtape[n].loop_active(0)`, or press the loop button on the panel |
| Tape boundary firing every ~18 s regardless of `looplen()` | crow metro time-cap bug | Already mitigated by `clock.run` based timer in `master.lua` |

## Defaults baked into `master.lua` (as of last deploy)

- Tape: `loop_len=1800` (30 min), `overdub=0.135` (8 h memory @ -20 dB),
  `echo_mode=0`, `rec_level=1.0`, `monitor_level=1.0`
- Tape transport: `record=1`, `play=1` on both, set in `init()`
- Clock: 2 Hz, 20 ms pulse, **staged but not auto-started** (call `cv_on()`)
- Sieve: residues `{{11,0},{13,5},{17,2},{19,7}}` union, chromatic 12-tone
  scale, `octaves=2`, `root=0.0`
- LFO triangle: `ticks=8192` (~68 min cycle at 2 Hz), `amp=5.0`
- Inputs: both `none` by default (call `cv_in(true)` to enable rate CV on input 1)

See `wtape_reference.md` for the full ii parameter table and
`layering.md` for the dB-rigorous decay design.

## Default behavior preferences

- **Don't auto-deploy or auto-restart things on the user's behalf**
  unless they explicitly ask. Recovery actions especially — confirm before
  destructive or potentially-disruptive operations.
- **Prefer the user driving druid** for one-off queries. We do the heavy
  lifting (build, deploy, complex multi-step probes); they handle the
  "type one command and tell me what it printed" stuff.
- **Document mistakes immediately.** If something bites us in the session,
  add it to this file before moving on. Future-Claude reads this on entry.
