#!/usr/bin/env python3
"""Recover crow from a stuck/spamming script.

Sends ^^k (kill Lua) and ^^c (clear flash) over USB serial with a concurrent
read-drainer thread to keep the host CDC buffer from choking.

If this fails repeatedly (writes never land), use the i2c jumper hardware
recovery — see README.md.
"""
import serial, time, threading, sys

PORT = '/dev/tty.usbmodem346F367835381'

def main():
    s = serial.Serial(PORT, 115200, timeout=0.05, write_timeout=2.0)
    time.sleep(0.3)

    stop = [False]
    def drain():
        while not stop[0]:
            try: s.read(8192)
            except Exception: pass
    threading.Thread(target=drain, daemon=True).start()

    print('--- ^^k (kill running Lua) ---')
    for _ in range(40):
        try: s.write(b'^^k\n'); s.flush()
        except Exception as e: print('write err:', e)
        time.sleep(0.05)

    time.sleep(0.5)

    print('--- ^^c (clear flash) ---')
    for _ in range(40):
        try: s.write(b'^^c\n'); s.flush()
        except Exception as e: print('write err:', e)
        time.sleep(0.05)

    time.sleep(0.5)

    print('--- ^^r (restart) ---')
    try: s.write(b'^^r\n'); s.flush()
    except Exception as e: print('write err:', e)

    stop[0] = True
    time.sleep(0.5)
    s.close()

    time.sleep(3.0)  # USB renumerates
    print('--- ping ---')
    s2 = serial.Serial(PORT, 115200, timeout=1.0)
    time.sleep(0.5)
    s2.reset_input_buffer()
    s2.write(b'print("alive")\n'); s2.flush(); time.sleep(0.5)
    out = s2.read(2048)
    n = out.count(b'event queue full')
    if n > 0:
        print(f'STILL FLOODING ({n} spam lines). Use hardware i2c jumper recovery.')
        sys.exit(1)
    print('crow recovered:', out[-100:])
    s2.close()

if __name__ == '__main__':
    main()
