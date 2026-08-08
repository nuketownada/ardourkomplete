#!/usr/bin/env python3
"""a61mon — decode Komplete Kontrol A61 HID input reports.

Field layout is taken from the device's own HID report descriptor, not from
reverse engineering, so it is authoritative for report structure. What it does
NOT tell us is which *bit index* corresponds to which physical control -- that
is what this tool captures.

Input report 0x01, 30 bytes total (1 ID + 29 payload):
    payload[0:5]    40 button bits          (upstream A25 code reads only 32)
    payload[5:21]   8 x u16, range 0..999   (knob touch/position -- unconfirmed)
    payload[21:25]  2 x u16, range 0..4095  (pitch bend, mod wheel -- unconfirmed)
    payload[25:27]  1 x u16, range 0..4095  (third analog -- pedal? unconfirmed)
    payload[27]     2 x u4,  range 0..15    (4-D encoder position + ? )
    payload[28]     1 x u8                  (unknown)

Usage:
    a61mon.py [seconds] [--raw]
"""
import os, select, struct, sys, time

DEV = "/dev/hidraw12"


def decode(p):
    """p = 29-byte payload (report ID already stripped)."""
    bits = []
    for byte_i in range(5):
        for bit_i in range(8):
            if p[byte_i] & (1 << bit_i):
                bits.append(byte_i * 8 + bit_i)
    knobs = list(struct.unpack("<8H", p[5:21]))
    pb, mod = struct.unpack("<2H", p[21:25])
    aux, = struct.unpack("<H", p[25:27])
    return {
        "bits": bits,
        "knobs": knobs,
        "pb": pb, "mod": mod, "aux": aux,
        "nib_lo": p[27] & 0x0F, "nib_hi": (p[27] >> 4) & 0x0F,
        "b28": p[28],
    }


def diff(old, new):
    """Human-readable description of what changed between two decodes."""
    out = []
    if old is None:
        return [f"initial: bits={new['bits']} knobs={new['knobs']} "
                f"pb={new['pb']} mod={new['mod']} aux={new['aux']} "
                f"nib={new['nib_hi']},{new['nib_lo']} b28={new['b28']}"]

    pressed = set(new["bits"]) - set(old["bits"])
    released = set(old["bits"]) - set(new["bits"])
    for b in sorted(pressed):
        out.append(f"BIT {b:2d} (byte {b//8} bit {b%8})  PRESS")
    for b in sorted(released):
        out.append(f"BIT {b:2d} (byte {b//8} bit {b%8})  release")

    for i, (a, b) in enumerate(zip(old["knobs"], new["knobs"])):
        if a != b:
            out.append(f"KNOBFIELD {i}  {a:4d} -> {b:4d}   (delta {b-a:+d})")

    for name in ("pb", "mod", "aux"):
        if old[name] != new[name]:
            out.append(f"{name.upper():4s}  {old[name]:4d} -> {new[name]:4d}"
                       f"   (delta {new[name]-old[name]:+d})")

    for name in ("nib_hi", "nib_lo"):
        if old[name] != new[name]:
            d = (new[name] - old[name]) % 16
            d = d if d <= 8 else d - 16
            out.append(f"{name}  {old[name]:2d} -> {new[name]:2d}   (step {d:+d})")

    if old["b28"] != new["b28"]:
        out.append(f"BYTE28  {old['b28']:3d} -> {new['b28']:3d}")
    return out


def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1][0].isdigit() else 60.0
    raw = "--raw" in sys.argv

    fd = os.open(DEV, os.O_RDWR | os.O_NONBLOCK)
    print(f"# listening on {DEV} for {dur:.0f}s -- go", flush=True)
    t0 = time.time()
    prev = None
    count = 0
    while time.time() - t0 < dur:
        r, _, _ = select.select([fd], [], [], 0.2)
        if not r:
            continue
        data = os.read(fd, 128)
        if not data or data[0] != 0x01 or len(data) < 30:
            if raw:
                print(f"  other report: {data.hex(' ')}", flush=True)
            continue
        count += 1
        cur = decode(data[1:30])
        t = time.time() - t0
        for line in diff(prev, cur):
            print(f"[{t:6.2f}] {line}", flush=True)
        if raw:
            print(f"          raw {data.hex(' ')}", flush=True)
        prev = cur
    print(f"# done -- {count} input reports", flush=True)
    os.close(fd)


if __name__ == "__main__":
    main()
