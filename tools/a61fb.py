#!/usr/bin/env python3
"""a61fb — framebuffer for the A61 128x32 OLED, and a geometry self-test.

FORMAT (derived on this unit, see docs/a61-hid-map.md):

  Panel is 128 x 32, 1 bpp. Output report 0xe0 is 265 bytes:
    [0]      report ID 0xe0
    [1]      start column (0 or 64)
    [5]      column count  (0x40 = 64)
    [7]      page count    (0x04 = 4 pages of 8 rows = 32 rows)
    [9:265]  256 data bytes

  Data is PAGE-MAJOR within a report:  data[page * 64 + col]
  Each byte is 8 VERTICAL pixels of one column within that page.

  POLARITY IS INVERTED: a SET bit renders DARK, a CLEAR bit renders LIT.
  So the encoder XORs 0xff at the end.

  Two reports (start column 0 and 64) cover the full 128-wide frame.

The only thing not yet pinned down is bit order within a byte -- whether bit 0
is the top row of the page or the bottom. `selftest` draws a diagonal, which
makes a wrong bit order obvious as a staircase.

Usage:
    a61fb.py selftest [seconds]   border + diagonal + square + corner marks
    a61fb.py flip     [seconds]   same, with bit order reversed
    a61fb.py clear                blank the panel (all lit -> all dark)
"""
import os
import sys
import time

from a61dev import find_device
W, H = 128, 32
PAGES = H // 8
COLS_PER_REPORT = 64


class FB:
    """1 = lit, in logical terms. Inversion for the panel happens in encode()."""

    def __init__(self):
        self.px = bytearray(W * H)

    def set(self, x, y, v=1):
        if 0 <= x < W and 0 <= y < H:
            self.px[y * W + x] = v

    def hline(self, x0, x1, y, v=1):
        for x in range(x0, x1 + 1):
            self.set(x, y, v)

    def vline(self, x, y0, y1, v=1):
        for y in range(y0, y1 + 1):
            self.set(x, y, v)

    def rect(self, x0, y0, x1, y1, v=1):
        self.hline(x0, x1, y0, v)
        self.hline(x0, x1, y1, v)
        self.vline(x0, y0, y1, v)
        self.vline(x1, y0, y1, v)

    def fill_rect(self, x0, y0, x1, y1, v=1):
        for y in range(y0, y1 + 1):
            self.hline(x0, x1, y, v)

    def line(self, x0, y0, x1, y1, v=1):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.set(x0, y0, v)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def region(self, x0, ypage0, w, hpages, msb_top=False, short=False):
        """One 265-byte 0xe0 report covering a sub-rectangle.

        Header is four u16 LE fields:
            [1:3] x offset in PIXELS
            [3:5] y offset in PAGES      (1 page = 8 rows)
            [5:7] width    in PIXELS
            [7:9] height   in PAGES
        Payload is w*hpages bytes, page-major: data[localpage * w + col].
        Must satisfy w * hpages <= 256.
        """
        assert w * hpages <= 256, "region exceeds the 256-byte payload"
        b = bytearray(265)
        b[0] = 0xE0
        b[1], b[2] = x0 & 0xFF, (x0 >> 8) & 0xFF
        b[3], b[4] = ypage0 & 0xFF, (ypage0 >> 8) & 0xFF
        b[5], b[6] = w & 0xFF, (w >> 8) & 0xFF
        b[7], b[8] = hpages & 0xFF, (hpages >> 8) & 0xFF
        data = bytearray(b"\xff" * 256)         # unused tail = dark
        for lp in range(hpages):
            for col in range(w):
                x = x0 + col
                v = 0
                for bit in range(8):
                    y = (ypage0 + lp) * 8 + bit
                    if 0 <= y < H and self.px[y * W + x]:
                        v |= 1 << ((7 - bit) if msb_top else bit)
                data[lp * w + col] = v ^ 0xFF   # panel: set bit = DARK
        b[9:265] = data
        # short=True sends only ID + 8 header + w*hpages bytes.
        # VERIFIED BROKEN on this unit: the kernel accepts the write without
        # error but the panel renders corrupt (pages dropped, lines broken).
        # Kept solely so the negative result stays reproducible -- do not use
        # it for anything real. Every 0xe0 report must be the full 265 bytes.
        return bytes(b[:9 + w * hpages]) if short else bytes(b)

    def encode_dirty(self, dirty_pages, msb_top=False):
        """Minimal report set covering the dirty pages.

        A report is fixed-size but carries up to 256 payload bytes, and a
        full-width band is 128 bytes per page -- so a 2-page band costs exactly
        what a 1-page band costs. Widening to 2 pages is free, which is what
        makes this beat a fixed top/bottom split:

            span = [min(dirty), max(dirty)];  n = max - min + 1
            n <= 2  -> 1 report:  (0, min, 128, 2)   widen, it is free
            n == 3  -> 2 reports
            n == 4  -> 2 reports                     (same as tb)

        Strictly <= a fixed two-halves split in every case, and strictly better
        for {1,2} -- a parameter name and its value on adjacent rows straddling
        the tb boundary, which this layout makes the common case. There are
        three possible 2-page bands (starting at page 0, 1 or 2); tb only ever
        uses two of them.

        PRECONDITION: every dirty region is FULL-WIDTH.

        This takes w=128 unconditionally, so it is optimal for text rows and
        nothing else. The true optimum is the dirty bounding box subject to
        w * h <= 256, and this loses to it whenever a dirty region is narrow
        and tall -- e.g. a 16px vertical level meter spanning all four pages
        costs 2 reports here, versus 1 for (x=112, y=0, w=16, h=4).

        If a narrow always-animating element is ever added, generalise this to
        track x-extent too. The failure is silent: nothing breaks, the report
        rate just quietly doubles.
        """
        pages = sorted(set(dirty_pages))
        if not pages:
            return []
        lo, hi = pages[0], pages[-1]
        n = hi - lo + 1
        if n <= 2:
            lo = min(lo, PAGES - 2)              # widen to 2, clamp to panel
            regions = [(0, lo, 128, 2)]
        else:
            regions = [(0, 0, 128, 2), (0, 2, 128, 2)]
        return [self.region(*r, msb_top=msb_top) for r in regions]

    def encode(self, msb_top=False, tiling="lr", short=False):
        """-> list of 0xe0 reports covering the whole panel.

        tiling "lr":   two 64x32 halves, left then right   (verified)
        tiling "tb":   two 128x16 halves, top then bottom  (cabl's Mikro split)
        tiling "quad": four 64x16 quadrants                (verified)
        tiling "rows": four full-width 128x8 page rows     (128 B each)

        "rows" is the interesting one for a driver: a full-width single page is
        128 x 1 = 128 bytes, and two rows is exactly the 256-byte ceiling. Four
        of them tile the panel with no partial-page arithmetic anywhere.
        """
        if tiling == "lr":
            regions = [(0, 0, 64, 4), (64, 0, 64, 4)]
        elif tiling == "tb":
            regions = [(0, 0, 128, 2), (0, 2, 128, 2)]
        elif tiling == "quad":
            regions = [(0, 0, 64, 2), (64, 0, 64, 2),
                       (0, 2, 64, 2), (64, 2, 64, 2)]
        elif tiling == "rows":
            regions = [(0, p, 128, 1) for p in range(PAGES)]
        else:
            raise SystemExit(f"unknown tiling {tiling!r}")
        return [self.region(*r, msb_top=msb_top, short=short) for r in regions]


def show(fb, secs, msb_top=False, tiling="lr", short=False):
    reports = fb.encode(msb_top, tiling, short)
    print(f"  {len(reports)} reports, sizes {[len(r) for r in reports]}", flush=True)
    t0 = time.time()
    errs = {}
    while time.time() - t0 < secs:
        for r in reports:
            try:
                fd = os.open(find_device(), os.O_RDWR)
                try:
                    os.write(fd, r)
                finally:
                    os.close(fd)
            except OSError as e:
                errs[e.errno] = errs.get(e.errno, 0) + 1
        time.sleep(0.25)
    if errs:
        print("errors:", errs)


def testimage():
    fb = FB()
    fb.rect(0, 0, W - 1, H - 1)               # 1px border, full extent
    fb.line(0, 0, W - 1, H - 1)               # diagonal: reveals bit order
    fb.fill_rect(100, 4, 107, 11)             # solid 8x8 block
    fb.fill_rect(4, 4, 7, 7)                  # small 4x4 near top-left
    return fb


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    cmd = sys.argv[1]
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0
    if cmd == "selftest":
        tiling = sys.argv[3] if len(sys.argv) > 3 else "lr"
        short = len(sys.argv) > 4 and sys.argv[4] == "short"
        print(f"border + diagonal + blocks, tiling={tiling}, short={short}",
              flush=True)
        show(testimage(), secs, msb_top=False, tiling=tiling, short=short)
    elif cmd == "flip":
        print("same image, bit order REVERSED (bit7 = top)", flush=True)
        show(testimage(), secs, msb_top=True)
    elif cmd == "clear":
        show(FB(), 1.0)
        print("panel cleared (all dark)")
    else:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
