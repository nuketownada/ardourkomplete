#!/usr/bin/env python3
"""a61pat — hold a STATIC pattern on the A61 panel until interrupted.

Timed sweeps proved a bad way to work with a human observer: you cannot
correlate "I saw it change" to a slot without the observer watching a clock.
Static patterns are describable at leisure, so every question here is answered
by looking, not by timing.

Panel is 128 x 32 (feature report 0xf8). Output report 0xe0 carries an 8-byte
header plus 256 data bytes, so a full frame at 1bpp (512 B) needs two writes.

Patterns:
  on          every pixel bit set
  off         every pixel bit clear
  blocks32    alternating 32-byte blocks -- THE LAYOUT DISCRIMINATOR.
              If a byte is 8 *vertical* pixels (page/column addressing) this
              renders as vertical bars. If a byte is 8 *horizontal* pixels
              (row-major) it renders as horizontal stripes.
  blocks8     alternating 8-byte blocks (finer version of the above)
  firstrep    first 0xe0 write all-on, second all-off -- shows how much of the
              panel a single report covers
  secondrep   inverse of firstrep
  halfdata    within each report, first 128 bytes on, last 128 off

Usage:  a61pat.py <pattern> [seconds]     (default: hold 600 s)
"""
import os
import sys
import time

DEV = "/dev/hidraw12"
COLS = [0, 64]          # two reports, 64 columns each
B5, B7 = 0x40, 0x04     # 64 columns, 4 pages


def data_for(name, rep_idx):
    d = bytearray(256)
    if name == "on":
        d[:] = b"\xff" * 256
    elif name == "off":
        pass
    elif name == "blocks32":
        for i in range(256):
            d[i] = 0xFF if (i // 32) % 2 == 0 else 0x00
    elif name == "blocks8":
        for i in range(256):
            d[i] = 0xFF if (i // 8) % 2 == 0 else 0x00
    elif name == "firstrep":
        d[:] = b"\xff" * 256 if rep_idx == 0 else b"\x00" * 256
    elif name == "secondrep":
        d[:] = b"\xff" * 256 if rep_idx == 1 else b"\x00" * 256
    elif name == "halfdata":
        d[:128] = b"\xff" * 128
    elif name == "corner":
        # Only bytes 0..31 of the FIRST report. Breaks every symmetry at once:
        # position gives the axis order, size confirms page-major (expect a
        # 32-wide x 8-tall block, i.e. a quarter wide and a quarter tall), and
        # an all-lit panel with one dark block means inverted polarity.
        if rep_idx == 0:
            d[0:32] = b"\xff" * 32
    elif name == "page0":
        # Whole first page of the first report: 64 wide x 8 tall.
        if rep_idx == 0:
            d[0:64] = b"\xff" * 64
    else:
        raise SystemExit(f"unknown pattern {name!r}")
    return bytes(d)


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    name = sys.argv[1]
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0

    reports = []
    for i, c in enumerate(COLS):
        b = bytearray(265)
        b[0] = 0xE0
        b[1] = c
        b[5] = B5
        b[7] = B7
        b[9:265] = data_for(name, i)
        reports.append(bytes(b))

    print(f"holding pattern {name!r} for {secs:g}s -- Ctrl-C to stop", flush=True)
    t0 = time.time()
    errs = {}
    while time.time() - t0 < secs:
        for r in reports:
            try:
                fd = os.open(DEV, os.O_RDWR)
                try:
                    os.write(fd, r)
                finally:
                    os.close(fd)
            except OSError as e:
                errs[e.errno] = errs.get(e.errno, 0) + 1
        time.sleep(0.25)                 # refresh slowly; enough to hold
    print(f"done; errors: {errs if errs else 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
