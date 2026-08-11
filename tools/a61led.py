#!/usr/bin/env python3
"""a61led — drive the A61 LEDs via HID output report 0x80.

The HID report descriptor declares 0x80 as an output report of 21 bytes,
each with logical range 0..127 -- matching the report ID and byte count
published by the komplementary-kontrol project for the A25.

That range once suggested brightness was a plain continuum. It is not that
simple: 0x20 and 0x7c are indistinguishable on an A61, and both sit near the
bottom of what the panel can clearly do, since the firmware's own power-on
animation runs a brightness wave across the buttons in roughly 16 steps whose
PWM shifts are visible. A wave means simultaneous *different* levels, so the
hardware does per-LED brightness even if report 0x80 does not obviously expose
it. Use `ramp` to see the whole value space at once rather than guessing one
level at a time -- 21 LEDs showing 21 different values in a single report is
the same trick the firmware animation uses, and one glance beats 21 round
trips.

Doubles as a diagnostic for the output path in general: if LEDs respond but
the display (report 0xe0) does not, the transport is fine and the display
header is wrong. If neither responds, output reports are not reaching the
device at all.

Usage:
    a61led.py all <level>       set every LED, level 0..127
    a61led.py one <idx> <level> set a single index, others off
    a61led.py sweep [dwell]     light each index in turn (default 1.5s)
    a61led.py ramp [start] [step]
                                led i = start + i*step, one report -- shows
                                21 levels side by side for comparison
    a61led.py raw v0 v1 ...     set explicit values, rest off
"""
import os
import sys
import time

from a61dev import find_device
NLEDS = 21


def send(values):
    assert len(values) == NLEDS
    fd = os.open(find_device(), os.O_RDWR)
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

    elif a[0] == "ramp":
        start = int(a[1], 0) if len(a) > 1 else 0
        step = int(a[2], 0) if len(a) > 2 else 6
        v = [(start + i * step) & 0xFF for i in range(NLEDS)]
        send(v)
        print(f"ramp start=0x{start:02x} step={step}:")
        for i, lvl in enumerate(v):
            print(f"  led {i:2d}  0x{lvl:02x}  {lvl:3d}")

    elif a[0] == "raw":
        v = [int(x, 0) & 0xFF for x in a[1:]]
        if len(v) > NLEDS:
            print(f"at most {NLEDS} values", file=sys.stderr)
            return 2
        v += [0] * (NLEDS - len(v))
        send(v)
        print("raw " + " ".join(f"{x:02x}" for x in v))

    else:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
