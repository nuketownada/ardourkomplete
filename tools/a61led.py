#!/usr/bin/env python3
"""a61led — drive the A61 LEDs via HID output report 0x80.

The HID report descriptor declares 0x80 as an output report of 21 bytes,
each with logical range 0..127 -- matching the report ID and byte count
published by the komplementary-kontrol project for the A25. The range being
0..127 rather than three discrete levels suggests brightness is a continuum.

Doubles as a diagnostic for the output path in general: if LEDs respond but
the display (report 0xe0) does not, the transport is fine and the display
header is wrong. If neither responds, output reports are not reaching the
device at all.

Usage:
    a61led.py all <level>       set every LED, level 0..127
    a61led.py one <idx> <level> set a single index, others off
    a61led.py sweep [dwell]     light each index in turn (default 1.5s)
"""
import os
import sys
import time

DEV = "/dev/hidraw12"
NLEDS = 21


def send(values):
    assert len(values) == NLEDS
    fd = os.open(DEV, os.O_RDWR)
    try:
        return os.write(fd, bytes([0x80]) + bytes(values))
    finally:
        os.close(fd)


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    if a[0] == "all":
        lvl = int(a[1], 0) if len(a) > 1 else 0x7e
        n = send([lvl] * NLEDS)
        print(f"all {NLEDS} LEDs -> 0x{lvl:02x} ({n} bytes written)")

    elif a[0] == "one":
        idx, lvl = int(a[1], 0), int(a[2], 0)
        v = [0] * NLEDS
        v[idx] = lvl
        send(v)
        print(f"LED index {idx} -> 0x{lvl:02x}, others off")

    elif a[0] == "sweep":
        dwell = float(a[1]) if len(a) > 1 else 1.5
        print(f"sweeping {NLEDS} indices, {dwell}s each "
              f"-- watch and note the order they light", flush=True)
        for i in range(NLEDS):
            v = [0] * NLEDS
            v[i] = 0x7e
            send(v)
            print(f"  index {i:2d}", flush=True)
            time.sleep(dwell)
        send([0] * NLEDS)
        print("done, all off")

    else:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
