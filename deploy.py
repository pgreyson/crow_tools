#!/usr/bin/env python3
"""Build and deploy a crow program.

  python3 deploy.py <program_name> [--run N] [--port /dev/tty.usbmodemXXXX]

Builds built/<program>.built.lua by concatenating modules/*.lua + programs/<program>.lua,
then uploads it to crow via the ^^s / ^^e protocol. With --run, also calls go() and
streams output for 30s.

The same combined build runs on every rack's crow. The tape (w/tape over i2c)
subsystem is inert when no w/tape is on the bus -- ii.wtape writes are
fire-and-forget -- so the video rack (no i2c) just ignores it and runs the
sieve + slow-LFO CV stack. Pick which crow to flash with --port; with no flag
we use DEFAULT_PORT if present, else auto-detect a crow by USB VID:PID.
"""
import serial, time, sys, os, glob, argparse
from serial.tools import list_ports

HERE = os.path.dirname(os.path.abspath(__file__))
# wtape rack's crow (serial 346F36783538). Default target; override with --port.
DEFAULT_PORT = '/dev/tty.usbmodem346F367835381'
CROW_VIDPID = (0x0483, 0x5740)   # STM32 USB CDC -- all crows enumerate as this


def resolve_port(explicit=None):
    """Pick a serial port: --port wins, else DEFAULT_PORT if present, else
    auto-detect a single crow by VID:PID. Errors if zero or many are found."""
    if explicit:
        return explicit
    if os.path.exists(DEFAULT_PORT):
        return DEFAULT_PORT
    found = [p.device for p in list_ports.comports()
             if (p.vid, p.pid) == CROW_VIDPID]
    if not found:
        print('no crow found: pass --port /dev/tty.usbmodemXXXX', file=sys.stderr)
        sys.exit(1)
    if len(found) > 1:
        print('multiple crows found, pass --port to choose one:', file=sys.stderr)
        for d in found:
            print(f'  {d}', file=sys.stderr)
        sys.exit(1)
    print(f'auto-detected crow at {found[0]}')
    return found[0]

def _minify(src):
    out = []
    for raw in src.split('\n'):
        s = raw.split('--', 1)[0].rstrip()       # strip line comments and trailing ws
        if s.strip() == '': continue              # drop blank lines
        out.append(s)
    return '\n'.join(out) + '\n'

def _read_requires(prog_src):
    # Returns the module list, or None if no directive at all. An empty
    # directive ('-- requires:') means "no modules" (e.g. a standalone
    # program) -- distinct from absent, which means "bundle everything".
    for line in prog_src.split('\n')[:5]:
        m = line.strip()
        if m.startswith('-- requires:'):
            return [x.strip() for x in m.split(':',1)[1].split(',') if x.strip()]
    return None

def build(program):
    out_path = os.path.join(HERE, 'built', f'{program}.built.lua')
    prog_path = os.path.join(HERE, 'programs', f'{program}.lua')
    if not os.path.exists(prog_path):
        print(f'no such program: {prog_path}', file=sys.stderr); sys.exit(1)
    prog_src = open(prog_path).read()
    needed = _read_requires(prog_src)
    if needed is None:   # no directive -> bundle every module
        needed = [
            os.path.splitext(os.path.basename(p))[0]
            for p in sorted(glob.glob(os.path.join(HERE, 'modules', '*.lua')))
        ]
    pieces = [f'--- {program}\n']
    for name in needed:
        path = os.path.join(HERE, 'modules', f'{name}.lua')
        if not os.path.exists(path):
            print(f'missing module: {name}', file=sys.stderr); sys.exit(1)
        pieces.append(_minify(open(path).read()))
    pieces.append(_minify(prog_src))
    src = ''.join(pieces)
    with open(out_path, 'w') as f: f.write(src)
    print(f'built: {out_path} ({len(src)} bytes, modules: {",".join(needed)})')
    return out_path, src

def upload(built_path, run_for=0, port=None):
    import subprocess
    port = port or DEFAULT_PORT
    # bail out of any pending upload mode left by a prior failure
    s = serial.Serial(port, 115200, timeout=0.5)
    time.sleep(0.3)
    for cmd in (b'^^e\n', b'^^c\n'):
        s.write(cmd); s.flush(); time.sleep(0.4)
        s.read(s.in_waiting or 0)
    s.close(); time.sleep(0.3)

    print(f'--- druid upload {built_path} ---')
    r = subprocess.run(['druid', 'upload', built_path],
                       capture_output=True, text=True, timeout=30)
    sys.stdout.write(r.stdout); sys.stderr.write(r.stderr)
    if r.returncode != 0:
        print(f'druid upload failed (rc={r.returncode})', file=sys.stderr); sys.exit(1)

    if run_for > 0:
        s = serial.Serial(port, 115200, timeout=0.3)
        time.sleep(0.5); s.reset_input_buffer()
        print(f'\n--- starting and streaming for {run_for}s ---')
        s.write(b'go(true)\n' if 'tapes' in open(built_path).read() else b'start()\n')
        s.flush()
        deadline = time.time() + run_for
        while time.time() < deadline:
            chunk = s.read(512)
            if chunk: sys.stdout.write(chunk.decode(errors='replace')); sys.stdout.flush()
        print('\n--- stopping ---')
        s.write(b'stop_all()\n' if 'tapes' in open(built_path).read() else b'stop()\n')
        s.flush(); time.sleep(0.5)
        s.close()

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('program')
    ap.add_argument('--run', type=int, default=0,
                    help='seconds to run go(true) after upload')
    ap.add_argument('--port', default=None,
                    help='crow serial port; default DEFAULT_PORT, else auto-detect')
    a = ap.parse_args()
    port = resolve_port(a.port)
    out_path, _ = build(a.program)
    upload(out_path, a.run, port)
