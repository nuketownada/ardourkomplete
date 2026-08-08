#!/usr/bin/env python3
"""Write a format-0 SMF containing one sysex message, for aplaymidi."""
import struct
import sys


def varlen(n):
    out = bytearray([n & 0x7F])
    n >>= 7
    while n:
        out.insert(0, (n & 0x7F) | 0x80)
        n >>= 7
    return bytes(out)


def make(sysex_bytes, path):
    assert sysex_bytes[0] == 0xF0 and sysex_bytes[-1] == 0xF7
    body = sysex_bytes[1:]                      # SMF stores everything after F0
    track = bytearray()
    track += b"\x00"                            # delta time
    track += b"\xf0" + varlen(len(body)) + body
    track += b"\x00\xff\x2f\x00"                # end of track
    data = b"MThd" + struct.pack(">IHHH", 6, 0, 1, 96)
    data += b"MTrk" + struct.pack(">I", len(track)) + bytes(track)
    open(path, "wb").write(data)
    return len(sysex_bytes)


if __name__ == "__main__":
    hexstr = sys.argv[1].replace(" ", "")
    path = sys.argv[2]
    sx = bytes.fromhex(hexstr)
    n = make(sx, path)
    print(f"wrote {path}: {n}-byte sysex {sx.hex(' ')}")
