# ardourkomplete

Native Instruments **Komplete Kontrol A61** support for Ardour, as an in-tree
control surface.

Phase 1 (protocol discovery) is complete: the device is fully mapped, including
the 128×32 OLED, which appears to be the first open-source solution for this
device generation on Linux. See [`docs/a61-hid-map.md`](docs/a61-hid-map.md) —
that document is the deliverable, and the C++ transplants from it.

## Layout

```
docs/a61-hid-map.md   the protocol map -- inputs, LEDs, display, sysex
kk-a61-ardour-plan.md the original phase plan
tools/                Python probes, all working against real hardware
flake.nix             dev shell for building Ardour from source
```

| Tool | |
|---|---|
| `a61fb.py` | framebuffer + `encode()` / `encode_dirty()` — **the piece that ports to C++** |
| `a61mon.py` | HID input decoder / capture |
| `a61led.py` | LED control (index == button bit index) |
| `a61mode.py` | mode switch, recovery-first |
| `a61pat.py` | static test patterns |
| `mksysex.py` | sysex → format-0 SMF, for `aplaymidi` |

## Building Ardour

The Ardour checkout is a **sibling** of this repo, not a subdirectory:

```
~/projects/ardour            fork of Ardour/ardour, for PRs upstream
~/projects/ardourkomplete    this repo
```

`flake.nix` here provides the dev shell; `ardour/dev` is a one-line wrapper that
activates it. Nothing else is added to the Ardour tree, so a PR cannot pick up
stray tooling — `dev` itself is in `.git/info/exclude`.

```sh
cd ~/projects/ardour
./dev ./waf configure --cxx17 --no-phone-home --ptformat
./dev ./waf -j$(nproc)
./dev ./gtk2_ardour/ardev          # run from the build tree
```

`./dev` with no arguments drops into an interactive shell.

### Why the flake is not in the Ardour tree

Two Nix details, both learned the hard way:

- A devShell does not have to live in the tree it builds. Keeping it out means
  one source of truth and nothing to accidentally commit.
- Nix's `git+file` fetcher only sees **tracked** files. An untracked `flake.nix`
  inside a git repo fails with *"To make it visible to Nix, run: git add
  flake.nix"*. The `path:` prefix in `dev` avoids that class of problem entirely.

The flake pins nixpkgs to the revision the host system already uses, so every
dependency is pre-realised and the shell opens instantly. It also sets what
nixpkgs' own `ardour` derivation sets and a devShell would otherwise miss:
`_GNU_SOURCE`, the versioned `serd`/`sratom`/`sord` include paths, and
`-lpthread`. It clears `AS`, because with it set waf passes `-D` defines to the
assembler and `libs/ardour` fails to build — nixpkgs carries a patch for this;
clearing the variable avoids touching the tree.

### Surface gating

`libs/surfaces/wscript` builds surfaces conditionally. Both gates our surface
needs are satisfied by the flake:

| Define | From | Gates |
|---|---|---|
| `HAVE_USB` | `libusb-1.0` | push2, contourdesign, launchpad_*, launchkey_4 |
| `HAVE_HIDAPI` | hidapi | maschine2 (also needs `--maschine`) |

Note `maschine2` requires an explicit `--maschine` opt-in, whereas the USB
surfaces build automatically. Which pattern the A61 surface should follow is a
Phase 2 decision — automatic is friendlier, and there is no reason for this one
to be opt-in.

## Contributing upstream

Ardour's GitHub repo accepts PRs, but maintainers **apply them by hand** — PRs
usually close as "unmerged" with a comment like *"manually rebased and merged."*
So keep the branch small, focused, and cleanly rebasable on `master`.

```
origin     github.com/nuketownada/ardour   (fork, push here)
upstream   github.com/Ardour/ardour        (push URL deliberately DISABLED)
```

A full clone is required — Ardour derives its version from `git describe`.

## Device notes

The keyboard boots in MIDI mode and does **not** remember interactive mode
across a replug. To recover a device left in a bad state:

```sh
printf '\xa0\x07\x00' > /dev/hidrawN      # N is not stable; match on 17cc:1750
```

Once interactive mode has been entered, the firmware stops drawing the panel and
never resumes, so anything using the display should blank it on teardown
(`tools/a61fb.py clear`).
