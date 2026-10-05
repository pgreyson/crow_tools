# crow_tools

General tooling for monome **crow** (firmware v4.0.5): reusable Lua modules,
composed programs, and a build/deploy pipeline. The flagship program
(`master`) drives two **w/tape** modules over i2c plus CV outputs (clock,
Xenakis sieve, slow triangle).

## One build, multiple racks

crow holds a single script in flash, so "all the functions on one crow" means
one combined build — `master` already bundles tape + clock + sieve + slow LFO.
The **same build runs on every rack's crow**:

- **wtape rack** — crow + two w/tape over i2c. Tape + CV stack both active.
- **video rack** — crow only, no w/tape, no i2c. The tape subsystem is inert:
  `ii.wtape` writes are fire-and-forget, so with nothing on the bus they go
  nowhere. The sieve + slow-LFO CV stack runs identically. No separate build
  needed.

Pick which crow to flash with `deploy.py --port`; see [Deploying](#deploying).
If flash size or the inert tape activity ever matters, a slim build is one
`-- requires:` line away (e.g. a `clock, sieve, lfo` program with no tape).

## Folder layout

```
crow_tools/
├── modules/        -- reusable Lua classes, declared as globals
│   ├── tapes.lua   -- two w/tapes as a stereo pair, sync metro, level control
│   ├── clock.lua   -- master clock generator (CV pulse + Lua subscribers)
│   ├── sieve.lua   -- Xenakis sieve (residues / predicate, scale-aware V/oct)
│   ├── lfo.lua     -- phase-stepped LFO (subscribes to a clock)
│   └── cv.lua      -- (unused; legacy per-output sequencer)
├── programs/
│   ├── master.lua     -- composes Tapes + Clock + Sieve + LFO; defines init()
│   └── slow_lfos.lua  -- standalone: 4 free-running ASL LFOs, no modules
├── built/          -- generated single-file bundles
├── deploy.py       -- build (concat + minify) and upload via druid
├── recovery.py     -- ^^k/^^c/^^r dance for stuck-script recovery
├── README.md       -- you are here
├── wtape_reference.md  -- full ii.wtape parameter reference
└── layering.md     -- dB-rigorous design of loop_len + erase_strength
```

Modules are concatenated into a single Lua file at build time. crow can't
`require` user files, so we declare classes as globals and bundle.

A program can declare which modules it needs with a top-line directive:

```lua
-- requires: tapes, clock, sieve, lfo
```

`deploy.py` reads that and only includes those modules. Unused modules cost
flash and slow down the script — keep the bundle tight. An **empty** directive
(`-- requires:`) means *no* modules — for a standalone program like
`slow_lfos`. **Absent** directive means bundle *everything* (legacy default).

## Hardware

| Thing | Value |
|---|---|
| crow USB tty | `/dev/tty.usbmodem346F367835381` (serial `346F36783538`) |
| crow firmware | `v4.0.5` (Lua 5.3) |
| Baud | 115200, USB CDC, VID:PID `0483:5740` |
| w/tape #1 i2c | `0x71` (default) |
| w/tape #2 i2c | `0x72` (alternate; see below) |

To put one w/tape on the alt i2c address (so two can coexist on the bus):

1. Power off the case.
2. Hold **Play + Down** while powering on.
3. (Revert with **Play + Up** at power-on.)

Verify both tapes are on the bus from druid:

```lua
ii.pullup(true)
ii.wtape.event = function(e, v) print('EV', e.name, e.device, v) end
ii.wtape[1].get('record')   -- should print EV record 1 0.0
ii.wtape[2].get('record')   -- should print EV record 2 0.0
```

Both `ii.wtape[n]` calls are silent if a tape isn't responding — getters
are the only diagnostic; fire-and-forget (`record(1)`, `play(1)` etc.) emit
no reply on the bus.

### To put a w/ module in tape mode (vs syn / del)

1. Hold **record + play + loop** (in that order) → enter the engine launcher.
2. Tap **record** to select the tape engine.
3. Hold **down** until lights "charge up" → tape engine loads.

A dim yellow light marks the active engine: record = tape, play = syn,
loop = del.

### i2c cable orientation matters

If the ribbon is reversed, getters return nothing and fire-and-forget calls
do nothing. Diagnose by trying both orientations.

### Audio I/O is per-module, not bussed

Each w/tape has its own L/R audio inputs on the panel. i2c carries control
only. To capture stereo across both tapes you need two audio cables (or a
stackcable / Y-split from a single source).

## crow_sim — run programs without the crow

`python3 crow_sim.py [program]` (default `sieve_dual`) loads the SAME built
source deploy.py flashes into a local Lua 5.4 VM (`pip install --user lupa`)
and serves a browser UI at http://localhost:8777: sliders for every sieve
parameter (calling the program's real druid functions), in1/in2 CV voltage
sliders, a time-scale multiplier (audition a 10-min cycle in seconds), live
CV traces (pitch/gate/saw), and the sieve_viz visualizations driven by the
program's own `dump()`.

Shimmed API surface: `output[n].volts`, `input[n].mode('stream')/.stream`,
`clock.run/sleep/cancel`, `print`. NOT simulated: ASL (`output[n].action`),
`metro`, `ii` — using them raises "not simulated". Stochastic draws are
bit-exact vs hardware (integer hash); float math is float64 here vs the
crow's float32, so timing/CV differ only in the last decimals. The sim never
opens serial — with ONE exception: the UI's "→ crow" button batch-pushes the
current param state to the hardware as druid commands (scale, registers,
root, gate_ratio, pitch_span, all dset/pset keys — NOT rate/cycle, which
come from rack CV), following the serial safety rules, single pass, aborts
if the crow doesn't echo (druid open).

`python3 test_sim.py` is the parameter-effect suite: every control exercised
through the sim in deterministic step mode, gate patterns printed as
inspectable strips (`x` onset, `-` held, `.` rest), 21 assertions.

## sieve_dual (video rack) — control reference

The video crow runs `programs/sieve_dual.lua`: two independent Xenakis
sieves — DURATION (rhythm: its member gaps are the note lengths) and PITCH
(its member values index a Scala scale). Moduli for each are sampled from a
hierarchical Gaussian-mixture distribution over the modulus axis; residues
from a von-Mises density/concentration/seed distribution. Boots idle.

**CV in:** in1 = rate (absolute event density, exp 0.05→16 Hz — notes/sec ≈
rate × dur density, independent of cycle). in2 = cycle (wall-clock pattern
length AND out3 saw period, exp 0.05 s→24 h).

**Out:** 1 = pitch (V/oct), 2 = gate (width = duration × `gate_ratio`),
3 = saw −5→+5 V period = cycle, 4 = free.

**druid:**

```
start()  stop()  status()  dump()
scale_list()          -- chromatic major_ji pentatonic bohlen_pierce ed19 ed32 harm32
                      --   penta_cluster (5 just-penta cores x 5 microtones +/-40c)
scale('harm32')
dset(key, v)          -- duration-sieve distribution;  pset(key, v) -- pitch sieve
  'center'    where the moduli distribution sits (rhythm/melody timescale)
  'spread'    how widely sampled peak centers scatter (log ratio)
  'n_peaks'   Gaussian components in the mixture
  'width'     peak width (overlapping lumps <-> sharp spikes)
  'dominance' 0 = equal peaks, 1 = one big + little ones
  'terms'     how many moduli drawn from the mixture
  'density'   fraction of residue classes firing (fullness)
  'conc'      residues clustered <-> even
  'seed'      re-rolls the cascade (deterministic)
pitch_span(n)  registers(n)  root(v)  gate_ratio(r)
rate_hz(hz)  cycle_s(s)  speed_v(v)  cycle_v(v)   -- test without patched CV
```

`python3 sieve_viz.py` fetches `dump()` and renders the terms as text
notation + an SVG page (distribution, residue rings, onset strip, pitch
contour). Close druid first — it eats the crow's replies.

## Deploying

```bash
python3 deploy.py master            # build + upload to crow flash
python3 deploy.py master --run 30   # also start it and stream output 30s
python3 deploy.py master --port /dev/tty.usbmodemXXXX   # target a specific crow
```

**Picking the crow** (`--port`): with two racks you have two crows on two
serial ports. With no `--port`, deploy targets the wtape rack's `DEFAULT_PORT`
if it's present, otherwise auto-detects a single crow by USB VID:PID
(`0483:5740`). If both crows are plugged into the same Mac at once, auto-detect
finds two and bails — pass `--port` to disambiguate. (`recovery.py` and
`health_check.py` still hardcode the wtape crow's port; edit their `PORT`
constant if you need them on the video rack.)

`deploy.py`:
1. Reads `-- requires:` from the program file.
2. Concatenates needed modules + program, strips comments and blank lines.
3. Writes `built/<program>.built.lua`.
4. Sends `^^e + ^^c` over serial first to bail out of any stuck upload state.
5. Shells out to `druid upload`. **Do not use a homegrown `^^s/^^e` writer
   — the upload protocol needs proper handshaking; druid handles flow
   control we don't.**

`druid upload` writes to flash and `init()` runs on every power-on.

## crow's `^^` commands (firmware v4.0.x dispatch table)

These bypass the Lua REPL — they're parsed by the USB-CDC layer directly,
so they work even when Lua is stuck or the queue is overflowing.

| Cmd  | Action |
|------|--------|
| `^^v` | print version |
| `^^i` | print identity |
| `^^p` | print currently loaded script |
| `^^s` | start script upload (followed by lines, ended with `^^e`) |
| `^^e` | end upload + run |
| `^^w` | write to flash |
| `^^c` | clear saved user script |
| `^^r` | soft restart (USB renumerates) |
| `^^k` | **kill running Lua** (no flash change) — stops any runaway script |
| `^^b` | **enter DFU bootloader** — for reflashing |
| `^^f` / `^^F` | load First / Flash script |

(Source: `monome/crow/lib/caw.c` `_find_cmd()`.)

## Recovery from a stuck script

Symptoms:
- USB serial spammed continuously with `event queue full!`.
- `print(...)` from the REPL doesn't echo back.
- USB power-cycling doesn't help — the bad script reloads from flash on boot.

**Causes seen so far:**
- Auto-running CV/metro that schedules `clock.run` coroutines faster than
  they drain. (Fixed in `master.lua` v2 by using ASL pulse actions instead
  of coroutines for short pulses.)
- Truncated script in flash (mid-upload abort) → syntax error on every boot.

**Recovery sequence**, easiest first:

1. **`^^k` to kill Lua, then `^^c` to clear flash.**
   ```
   python3 recovery.py
   ```
   Use a **concurrent read-drainer thread** while writing — the spam
   chokes the host's CDC buffer otherwise. Even with the drainer this can
   take dozens of attempts before a write lands; the spam is winning the
   buffer race.

2. **`^^b` to force DFU**, then `druid firmware` or `dfu-util` to reflash.
   Same race conditions as above.

3. **i2c jumper (hardware, no soldering needed).** Pull crow from the
   case, on the rear i2c header bridge a center signal pin to a ground pin
   (ground = pin nearest the power header / white stripe), reinsert power.
   Crow boots straight to DFU, skipping Lua entirely. Then `druid firmware`
   to reflash. Documented as the bulletproof path on
   [monome.org/docs/crow/manual-update](https://monome.org/docs/crow/manual-update/).

## Pitfalls when writing crow Lua

These cost us hours; don't repeat them.

- **`clock.run` inside a high-rate metro is dangerous.** Each call queues
  a coroutine event. At 4–8 Hz it's fine; if anything pushes the rate up
  (e.g. a CV-controlled clock with input drifting high), coroutines pile
  up and the event queue overflows. Prefer `output[n].action = { to(...) }`
  ASL actions for short pulses — they run in the DAC scheduler, not the
  event queue.
- **Input streams at high rates** (e.g. `input[n].mode('stream', 0.05)`)
  add 20 callbacks/sec on top of everything else. Default to slow (0.5s
  or more) or off; let the user opt in.
- **Don't auto-start CV in `init()`.** If init() crashes the runtime (e.g.
  by overflowing the queue) you can't recover without DFU. Have init() set
  up state only; expose `cv_on()` / `cv_off()` for the user to start things
  from druid.
- **Avoid global names that shadow ASL primitives.** `loop`, `to`, `held`,
  `times`, `lfo`, `pulse`, `wait`, `here` are all globals in crow's
  scripting environment. If you define `function loop(s) ... end` you
  break ASL.
- **Crow can't `require` user modules.** Concatenate at build time and
  declare classes as globals (no `local M = {}` modules).
- **Flash script has a size limit.** ~8 KB used to be the cap; v4.0.5 is
  larger but exact bound is unclear. Keep bundles slim — strip comments,
  inline only the modules a program uses.
- **`^^s`/`^^e` upload protocol is fragile if you write it yourself.**
  Use `druid upload`. Killed mid-write, it leaves a truncated script in
  flash with a syntax error that crow tries to parse on every boot.
- **`metro.init{ time = N }` silently caps `N` at ~18 seconds** in firmware
  v4.0.5. Set `time = 60` or `time = 1800` and the metro still fires every
  ~18 s. Status output and getters report the value you set, but the metro
  doesn't honor it. **Use `clock.run(function() while true do clock.sleep(N); ... end end)` for any boundary timer longer than ~15 s.**
  This bit us hard on tape loop boundaries — see `programs/master.lua`'s
  `looplen()`.
- **`WARNING_clear_tape` is a multi-second blocking SD I/O.** Sending
  `record(1)`/`play(1)`/`timestamp(0)` follow-ups within a few seconds of
  the clear can leave the tape transport hung. Recovery requires
  power-cycling the eurorack case. Wait ≥30 s after each clear.

## REPL cheat sheet for `master`

Once `master.lua` is on flash, drop into druid (`druid` in a terminal) and
type any of:

```lua
status()                          -- print current state
-- tape
looplen(0)                        -- ambient: continuous record, no re-zero
looplen(30)                       -- short-loop: re-zero every 30s
overdub(0.5)                      -- 0=overdub forever, 1=overwrite each pass
reclevel(1.0); monlevel(1.0)
rec_on(); rec_off(); play_on(); play_off(); tape_off()
-- clock
rate(8); pw(20)
-- sieve
residues({{3,0},{5,2}}, 'union')  -- or 'intersection'
pred(function(n) return n%7 == n%5 end)
scale({0,3,5,7,10}); octaves(3); root(0.5)
invert(true); gate_ms(50); reset_step()
-- slow triangle
tri_log(20)                       -- 2^20 ticks/cycle ≈ 73h at 4 Hz
tri_shape('sine')                 -- triangle | sine | saw | square
tri_amp(2.5); tri_center(0)
```

## Other notes

- crow's CDC layer accepts `^^` commands the moment USB enumerates, before
  Lua's `init()` runs. **There is no boot grace period** — the race to
  send `^^c` before init() floods the queue is technically winnable but
  in practice has been reliably losing for us.
- `druid clearscript` requires crow already in DFU. For clearing a running
  script, use `^^c` over serial.
- Tape position is queryable via `ii.wtape[n].get('timestamp')`. Units
  appear to be seconds but verify on-device before trusting.
- w/tape's tape is a **continuous loop** (~3h per tape on w/2.x firmware).
  No "end of tape" event. All sync must be timer-driven.
- `set_log_ticks(x)` on the LFO sets the period to `2^x` clock ticks. At
  the default 4 Hz clock that's 0.25s × 2^x = up to ~73 hours at x=20.
