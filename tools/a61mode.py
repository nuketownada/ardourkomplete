#!/usr/bin/env python3
"""a61mode — switch the Komplete Kontrol A61 between MIDI and Interactive mode.

RECOVERY. If the device becomes unresponsive, gets stuck, or stops sending
MIDI, run this and it should come back:

    python3 a61mode.py midi

The same thing with no dependencies at all, in case this file is unavailable.
Find the node first -- do not guess it, and do not reuse a number you saw
earlier, because hidraw numbering is not stable across replugs:

    grep -l 17CC:00001750 /sys/class/hidraw/hidraw*/device/uevent
    printf '\\xa0\\x07\\x00' > /dev/hidrawN

A power-cycle (unplug/replug USB) is the other recovery path and is expected
to reset the device to its default MIDI mode.

Background: output report 0xa0 is declared by the device's own HID report
descriptor as 2 payload bytes, which matches the 3-byte sequences documented
(but never shipped) by hugovangalen/komplementary-kontrol:
    a0 07 00  -> MIDI mode (default; firmware owns knobs/wheels/screen)
    a0 03 04  -> Interactive mode (host takes over)
Both are now verified on this A61: the Ardour surface enters interactive mode
at startup and restores MIDI mode on exit, and the keyboard comes back. The
warning below dates from when the interactive command was only observed on
someone else's A25.
"""
import os
import sys

from a61dev import find_device

MODES = {
    "midi":        (0xa0, 0x07, 0x00),
    "interactive": (0xa0, 0x03, 0x04),
}


def send(report):
    fd = os.open(find_device(), os.O_RDWR)
    try:
        n = os.write(fd, bytes(report))
    finally:
        os.close(fd)
    return n


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in MODES:
        print(f"usage: {sys.argv[0]} {{midi|interactive}}", file=sys.stderr)
        print("\n  midi         a0 07 00   default, restores firmware control",
              file=sys.stderr)
        print("  interactive  a0 03 04   host takeover (knobs + screen to host)",
              file=sys.stderr)
        return 2

    mode = sys.argv[1]
    report = MODES[mode]
    hexs = " ".join(f"{b:02x}" for b in report)

    if mode == "interactive":
        print("!! Handing the knobs and screen to the host.")
        print(f"!! If anything goes wrong: {sys.argv[0]} midi")
        print(f"!! or:                     printf '\\xa0\\x07\\x00' > {find_device()}")

    n = send(report)
    print(f"sent {hexs} to {find_device()} ({n} bytes) -> {mode} mode")
    return 0


if __name__ == "__main__":
    sys.exit(main())
