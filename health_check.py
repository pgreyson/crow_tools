#!/usr/bin/env python3
"""Read-only health probe for the master program. Safe by construction:
context-managed serial, hard timeouts on every read, bounded loop count.
No kill targets here — if interrupted normally, the close happens.
"""
import serial, time, re, sys

PORT = '/dev/tty.usbmodem346F367835381'

def main():
    with serial.Serial(PORT, 115200, timeout=0.5) as s:
        time.sleep(0.3)
        s.reset_input_buffer()

        # 1. crow alive?
        s.write(b'^^v\n'); s.flush(); time.sleep(0.3)
        r = s.read(256).decode(errors='replace').strip()
        print(f'^^v reply: {r!r}')
        if 'version' not in r:
            print('FAIL: crow not responding to protocol layer')
            return

        # 2. master status
        s.write(b'status()\n'); s.flush(); time.sleep(0.6)
        print('--- status() ---')
        print(s.read(2048).decode(errors='replace').strip())

        # 3. tape getters: are both rolling, and is loop_active set?
        s.write(b'ii.wtape.event = function(e,v) print(e.device, e.name, v) end\n')
        s.flush(); time.sleep(0.3)
        s.read(2048)  # drain handler-set echo

        print('--- tape getters ---')
        for tape in (1, 2):
            for q in ('record', 'play', 'loop_active', 'timestamp'):
                s.write(f'ii.wtape[{tape}].get("{q}")\n'.encode())
                s.flush()
                time.sleep(0.4)
        time.sleep(0.8)
        print(s.read(4096).decode(errors='replace').strip())

        # 4. monitor 30s for unexpected re-zero (catches ~18s and longer)
        print('--- monitor 30s; with looplen=1800 there should be NO rezero ---')
        last = None
        rezero_events = 0
        for i in range(7):  # 7 samples × 5s ≈ 30s
            s.reset_input_buffer()
            s.write(b'ii.wtape[1].get("timestamp")\n'); s.flush()
            time.sleep(5.0)
            out = s.read(512).decode(errors='replace')
            m = re.search(r'1\s+timestamp\s+([0-9.]+)', out)
            if m:
                v = float(m.group(1))
                rez = ''
                if last is not None and v < last - 1:
                    rezero_events += 1
                    rez = '  <-- REZERO'
                print(f't={i*5:3d}s  T1={v:9.3f}{rez}')
                last = v
            else:
                print(f't={i*5:3d}s  (no reply)')
        print()
        print(f'rezero events in 30s window: {rezero_events}')
        print('expected: 0 (looplen is 1800s)')

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'ERR: {type(e).__name__}: {e}', file=sys.stderr)
        sys.exit(1)
