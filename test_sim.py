#!/usr/bin/env python3
"""test_sim: parameter-effect tests for sieve_dual, run in crow_sim's
deterministic step mode (Sim.advance — no wall clock, no threads, no serial).

Each test renders the gate pattern as a VISUALLY INSPECTABLE strip —
one character per tick slot, 'x' = note onset, '-' = gate held, '.' = rest —
then asserts a measurable effect of the parameter. Read the strips; trust
the asserts.

Run:  python3 test_sim.py
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from crow_sim import Sim, push_commands

PASS, FAIL = 0, []

def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")

def fresh(**settings):
    """New sim, engine started, params applied, settled one tick."""
    sim = Sim('sieve_dual')
    sim.call('start')
    for fn, args in settings.get('calls', []):
        sim.call(fn, *args)
    if 'cv1' in settings: sim.in_volts[1] = settings['cv1']
    if 'cv2' in settings: sim.in_volts[2] = settings['cv2']
    sim.advance(1.0)          # let input streams deliver + realign
    return sim

def strip(sim, seconds, chars=72):
    """Gate trace -> one char per tick slot: x onset, - held, . rest."""
    st = sim.dump_state()
    rate = st['rate']
    t0 = sim.vtime
    mark2 = len(sim.traces[2])
    sim.advance(seconds)
    events = sim.traces[2][mark2:]          # (vtime, volts) transitions
    nslots = min(chars, int(seconds * rate))
    out = []
    level = sim.traces[2][mark2 - 1][1] if mark2 > 0 else 0.0
    ei = 0
    for slot in range(nslots):
        slot_t0, slot_t1 = t0 + slot / rate, t0 + (slot + 1) / rate
        onset = False
        while ei < len(events) and events[ei][0] < slot_t1:
            if events[ei][1] > 2.5 and level <= 2.5:
                onset = True
            level = events[ei][1]
            ei += 1
        out.append('x' if onset else ('-' if level > 2.5 else '.'))
    return ''.join(out), st

def onsets(s): return s.count('x')

def pitch_set(sim, seconds):
    mark = len(sim.traces[1])
    sim.advance(seconds)
    return [v for _, v in sim.traces[1][mark:]]

print("== rate (in1 CV): absolute density — onsets/sec scales with rate ==")
a = fresh(cv1=-1.0); sa, sta = strip(a, 40)
b = fresh(cv1=1.0);  sb, stb = strip(b, 40)
print(f"  cv1=-1V rate={sta['rate']:.2f}: {sa}")
print(f"  cv1=+1V rate={stb['rate']:.2f}: {sb}")
ra = onsets(sa) / max(1, len(sa)) * sta['rate']
rb = onsets(sb) / max(1, len(sb)) * stb['rate']
check("rate raises notes/sec", rb > ra * 1.5, f"{ra:.2f} vs {rb:.2f}")

print("== cycle (in2 CV): span tracks rate*cycle ==")
a = fresh(cv2=-2.0); _, sta = strip(a, 5)
b = fresh(cv2=2.0);  _, stb = strip(b, 5)
print(f"  cv2=-2V: cycle={sta['cycle']:.1f}s span={sta['span']}   cv2=+2V: cycle={stb['cycle']:.1f}s span={stb['span']}")
check("cycle changes span", stb['span'] > sta['span'] * 2)

print("== timescale: host time_scale accelerates virtual time (threaded) ==")
import threading, time as _time
sim = fresh()
sim.time_scale = 1.0
threading.Thread(target=sim.loop, daemon=True).start()
v0 = sim.vtime; _time.sleep(0.5); d1 = sim.vtime - v0
sim.time_scale = 10.0
v0 = sim.vtime; _time.sleep(0.5); d10 = sim.vtime - v0
sim.running = False
print(f"  0.5s wall at x1 -> {d1:.2f} vsec;  at x10 -> {d10:.2f} vsec")
check("timescale multiplies vtime", 6 < d10 / max(d1, 1e-9) < 14, f"ratio {d10/max(d1,1e-9):.1f}")

print("== dur density: onset fraction tracks the knob ==")
a = fresh(calls=[('dset', ['density', 0.15])]); sa, _ = strip(a, 40)
b = fresh(calls=[('dset', ['density', 0.7])]);  sb, _ = strip(b, 40)
print(f"  density 0.15: {sa}\n  density 0.70: {sb}")
check("density raises onset fraction", onsets(sb) > onsets(sa) * 1.5,
      f"{onsets(sa)} vs {onsets(sb)}")

print("== dur seed: re-rolls the pattern ==")
a = fresh(calls=[('dset', ['seed', 0.1])]); sa, _ = strip(a, 30)
b = fresh(calls=[('dset', ['seed', 0.6])]); sb, _ = strip(b, 30)
print(f"  seed 0.1: {sa}\n  seed 0.6: {sb}")
check("seed changes pattern", sa != sb)

print("== dur center: moduli move up the axis ==")
a = fresh(calls=[('dset', ['center', 5])]);  _, sta = strip(a, 2)
b = fresh(calls=[('dset', ['center', 30])]); _, stb = strip(b, 2)
import sieve_viz
ma = sieve_viz.derive(sta)['dur']['moduli']; mb = sieve_viz.derive(stb)['dur']['moduli']
print(f"  center 5: moduli={ma}   center 30: moduli={mb}")
check("center moves moduli", sum(mb)/len(mb) > sum(ma)/len(ma) * 1.5)

print("== dur terms: number of moduli drawn ==")
a = fresh(calls=[('dset', ['terms', 2])]); _, sta = strip(a, 2)
b = fresh(calls=[('dset', ['terms', 6])]); _, stb = strip(b, 2)
ma = sieve_viz.derive(sta)['dur']['moduli']; mb = sieve_viz.derive(stb)['dur']['moduli']
print(f"  terms 2: {ma}   terms 6: {mb}")
check("terms sets moduli count", len(ma) == 2 and len(mb) == 6, f"{len(ma)},{len(mb)}")

print("== dur n_peaks/spread/width/dominance/conc: plumbed to the engine ==")
for key, va, vb in (('n_peaks', 1, 5), ('spread', 0.1, 1.2), ('width', 0.05, 0.8),
                    ('dominance', 0.0, 1.0), ('conc', 0.0, 1.0)):
    a = fresh(calls=[('dset', [key, va])]); da = a.dump_state()['dur'][key if key != 'n_peaks' else 'n_peaks']
    b = fresh(calls=[('dset', [key, vb])]); db = b.dump_state()['dur'][key if key != 'n_peaks' else 'n_peaks']
    check(f"dset {key} reaches engine", abs(float(da) - va) < 0.01 and abs(float(db) - vb) < 0.01,
          f"{da} / {db}")

print("== pitch terms / seed / density: gamut changes ==")
a = fresh(calls=[('pset', ['terms', 2])]); _, sta = strip(a, 2)
b = fresh(calls=[('pset', ['terms', 6])]); _, stb = strip(b, 2)
ma = sieve_viz.derive(sta)['pitch']['moduli']; mb = sieve_viz.derive(stb)['pitch']['moduli']
print(f"  pitch terms 2: {ma}   pitch terms 6: {mb}")
check("pitch terms sets moduli count", len(ma) == 2 and len(mb) == 6)
a = fresh(calls=[('pset', ['seed', 0.1])])
b = fresh(calls=[('pset', ['seed', 0.9])])
pa = set(round(v, 3) for v in pitch_set(a, 30)); pb = set(round(v, 3) for v in pitch_set(b, 30))
check("pitch seed changes note set", pa != pb, f"{sorted(pa)[:5]} vs {sorted(pb)[:5]}")

print("== pitch traversal: NOT monotonic (stride fix) ==")
a = fresh(cv1=1.0)
vs = pitch_set(a, 30)
print(f"  first 12 pitches: {[round(v,2) for v in vs[:12]]}")
check("pitch leaps both ways", vs[:10] != sorted(vs[:10]) and len(vs) >= 10)

print("== registers: pitch range ==")
a = fresh(calls=[('registers', [1])]); pa = pitch_set(a, 40)
b = fresh(calls=[('registers', [4])]); pb = pitch_set(b, 40)
ra_, rb_ = max(pa) - min(pa), max(pb) - min(pb)
print(f"  registers 1: range {ra_:.2f} V   registers 4: range {rb_:.2f} V")
check("registers widens range", rb_ > ra_ + 0.9)

print("== root: shifts everything ==")
a = fresh(); pa = min(pitch_set(a, 20))
b = fresh(calls=[('root', [1.0])]); pb = min(pitch_set(b, 20))
check("root shifts pitch floor", abs((pb - pa) - 1.0) < 0.2, f"{pa:.2f} -> {pb:.2f}")

print("== scale: changes the tuning set ==")
a = fresh(); pa = set(round(v, 3) for v in pitch_set(a, 30))
b = fresh(calls=[('scale', ['penta_cluster'])]); pb = set(round(v, 3) for v in pitch_set(b, 30))
check("scale changes note set", pa != pb)

print("== gate_ratio: high fraction of the gate ==")
a = fresh(calls=[('gate_ratio', [0.2])]); sa, _ = strip(a, 40)
b = fresh(calls=[('gate_ratio', [0.95])]); sb, _ = strip(b, 40)
ha = (sa.count('-') + sa.count('x')) / max(1, len(sa))
hb = (sb.count('-') + sb.count('x')) / max(1, len(sb))
print(f"  ratio 0.2 : {sa}\n  ratio 0.95: {sb}")
check("gate_ratio lengthens gates", hb > ha + 0.15, f"{ha:.2f} vs {hb:.2f}")

print("== pitch_span: sequence length ==")
a = fresh(calls=[('pitch_span', [16])]); sta = a.dump_state()
b = fresh(calls=[('pitch_span', [128])]); stb = b.dump_state()
na = len(sieve_viz.derive(sta)['pitch']['members']); nb = len(sieve_viz.derive(stb)['pitch']['members'])
print(f"  span 16: {na} members   span 128: {nb} members")
check("pitch_span scales gamut", nb > na * 2)

print("== rapid rate change: responds mid-sleep (chunked sleep) ==")
sim = fresh(cv1=-5.0)                 # rate 0.05 Hz -> 20 s tick sleeps
sim.advance(3.0)                      # engine is now mid-long-sleep
sim.in_volts[1] = 5.0                 # crank to max
sim.advance(1.0)                      # stream delivers + settle window
mark = len(sim.traces[2])
sim.advance(3.0)
ticks = sum(1 for t, v in sim.traces[2][mark:] if v > 2.5)
print(f"  onsets in 3 vsec after cranking 0.05 -> 16 Hz: {ticks}")
check("rate change applies mid-sleep", ticks >= 5, f"got {ticks} (stale-sleep bug would give ~0)")

print("== rapid knob wiggle: no reset storm (settle-based respan) ==")
sim = fresh(cv1=2.0)
sim.advance(20.0)
step_before = sim.dump_state()['step']
for i in range(12):                   # wiggle in1 hard for ~2.4 vsec
    sim.in_volts[1] = 2.0 if i % 2 else -2.0
    sim.advance(0.2)
step_during = sim.dump_state()['step']
sim.in_volts[1] = -2.0                # settle
sim.advance(3.0)
step_after = sim.dump_state()['step']
print(f"  step before wiggle={step_before}  during={step_during}  after settle={step_after}")
check("no reset during wiggle", step_during >= step_before,
      f"{step_during} < {step_before} (reset storm)")
check("respan after settle", step_after < step_during + 60,
      f"settled realign missing? {step_during} -> {step_after}")

print("== push_commands: batch reproduces the full param state ==")
st = fresh().dump_state()
cmds = push_commands(st)
print("  " + "\n  ".join(cmds[:6]) + f"\n  ... ({len(cmds)} total)")
check("push covers all params", len(cmds) == 5 + 18 and any("dset('center'" in c for c in cmds))

print(f"\n{PASS} passed, {len(FAIL)} failed" + (f": {FAIL}" if FAIL else ""))
sys.exit(1 if FAIL else 0)
