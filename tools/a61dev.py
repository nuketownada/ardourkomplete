#!/usr/bin/env python3
"""Find a Komplete Kontrol A-Series hidraw node by USB vendor and product id.

hidraw numbers are handed out in enumeration order and are not stable. They
move on replug, on reboot, and whenever some unrelated HID device happens to
appear first.

Every tool here used to hardcode /dev/hidraw12. By 2026-08-10 that node had
become an Intel sensor hub while the A61 sat on hidraw8 -- so the recovery
command this repo documents for a stuck keyboard would have written a
mode-switch report into an entirely different device. The ids are the only
stable identifier, so resolve on those.

Run this file directly to list what it can see:

    python3 tools/a61dev.py

Override the choice with A61_HIDRAW=/dev/hidrawN, which is also how to pick one
when several A-Series keyboards are attached.
"""
import glob
import os

VENDOR = 0x17CC

# One device in three keybed sizes -- the report layout is identical across
# them, so any of these is equally usable by these tools. See
# docs/phase-2-plan.md for the evidence behind that claim.
PRODUCTS = {
    0x1730: "Komplete Kontrol A25",
    0x1740: "Komplete Kontrol A49",
    0x1750: "Komplete Kontrol A61",
}

ENV = "A61_HIDRAW"

_cached = None


def _hid_id(uevent_path):
    """(vendor, product) from a hidraw uevent, or None if unreadable."""
    try:
        with open(uevent_path) as f:
            for line in f:
                if line.startswith("HID_ID="):
                    # HID_ID=bus:vendor:product, hex, e.g. 0003:000017CC:00001750
                    parts = line.partition("=")[2].strip().split(":")
                    if len(parts) == 3:
                        return int(parts[1], 16), int(parts[2], 16)
    except (OSError, ValueError):
        pass
    return None


def scan():
    """Every A-Series hidraw node present, as a list of (devnode, model)."""
    found = []
    for sysdir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        ids = _hid_id(os.path.join(sysdir, "device", "uevent"))
        if ids and ids[0] == VENDOR and ids[1] in PRODUCTS:
            found.append(("/dev/" + os.path.basename(sysdir), PRODUCTS[ids[1]]))
    return found


def find_device():
    """The node to talk to, or exit with something the reader can act on."""
    global _cached
    if _cached:
        return _cached

    override = os.environ.get(ENV)
    if override:
        _cached = override
        return _cached

    found = scan()

    if not found:
        wanted = ", ".join(f"{VENDOR:04x}:{pid:04x}" for pid in sorted(PRODUCTS))
        raise SystemExit(
            f"no Komplete Kontrol A-Series device found (looked for {wanted}).\n"
            f"Is it plugged in? Force a node with {ENV}=/dev/hidrawN."
        )

    if len(found) > 1:
        listing = "\n".join(f"  {dev}  {model}" for dev, model in found)
        raise SystemExit(
            f"more than one A-Series device is attached:\n{listing}\n"
            f"Choose one with {ENV}=/dev/hidrawN."
        )

    _cached = found[0][0]
    return _cached


if __name__ == "__main__":
    devices = scan()
    if not devices:
        raise SystemExit("no Komplete Kontrol A-Series device found")
    for dev, model in devices:
        print(f"{dev}\t{model}")
