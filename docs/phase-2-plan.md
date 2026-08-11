# Phase 2 — Ardour surface module

Supersedes Phase 2 of [`../kk-a61-ardour-plan.md`](../kk-a61-ardour-plan.md), which
predates both the Phase 1 findings and the device-family research below.

**Exit criterion:** the module builds by default, loads in a locally-built
Ardour, appears in Preferences → Control Surfaces, and logs every control.

---

## Status — resume here

Written 2026-08-10; build verified same day. **The code compiles and links
clean. It has never been loaded by Ardour or seen the hardware.**

| | |
|---|---|
| `waf configure` | ✅ succeeded, with `--cxx17 --no-phone-home --ptformat --maschine` |
| `waf` build | ✅ **`'build' finished successfully`** — 15m40s throttled to `-j4`, then 9m21s unthrottled on Josh's rerun. All three sources compiled and `libardour_komplete_kontrol_a.so` linked, with **zero warnings and zero errors attributed to our files** |
| Symbols resolve | ✅ all 198 undefined symbols in the `.so` are satisfied by what Ardour maps at runtime (see below) |
| Loads in Ardour | ❌ not attempted — needs a display |
| Hardware trace | ❌ not attempted — needs Josh at the desk |

None of the three anticipated compile errors materialised. The `_()`/`X_()`
include ordering held; omitting `libgtkmm2ext`/`libytkmm` from `obj.use` linked
fine; the bundled hidapi is 0.15 and exports `hid_get_report_descriptor` at
`libs/hidapi/hidapi/hidapi.h:602`.

One bug was found and fixed by inspection before the build: `string_compose`
treats `std::hex` as a *positional argument* that consumes a placeholder (see
`libs/ardour/disk_reader.cc:597` for the tree's idiom), so the original
`string_compose ("%1", std::hex, pid)` would have printed the manipulator and
dropped the value. `open_device()` now formats the USB id with `snprintf` into
a local `usbid` buffer instead.

Both repos still have **uncommitted working-tree changes** — nothing has been
committed on either side:

```
~/projects/ardourkomplete   M README.md          ?? docs/phase-2-plan.md
~/projects/ardour           M gtk2_ardour/ardev_common.sh.in
  (branch komplete-kontrol-a) M libs/ardour/ardour/debug.h
                            M libs/ardour/debug.cc
                            M libs/surfaces/wscript
                            ?? libs/surfaces/komplete_kontrol_a/
```

**Build unthrottled.** An earlier draft of this document told you to use `-j4`
and never `-j$(nproc)`, on the theory that a parallel rebuild had driven the
machine's load average past 100 and made the desktop unusable. That was a
misdiagnosis. The stall came from a resource exhaustion bug in the tooling
running at the time, compounded by a NixOS system rebuild running
concurrently — not from `waf`. Unthrottled finished in **9m21s** against
**15m40s** for the same work at `-j4`.

```sh
cd ~/projects/ardour
./dev ./waf
```

What *is* true is that `libs/ardour/debug.cc` and `libs/ardour/ardour/debug.h`
are the expensive edits in this changeset — adding a surface `DebugBits`
requires touching both, and that forces a near-full rebuild of libardour. Batch
anything else that touches core headers alongside that edit. Worth checking
that a system rebuild is not already running before starting a long build.

### How the symbol check was done, and why not `dlopen`

A standalone `dlopen` of the module cannot work and its failure means nothing:
it pulls in `libardour.so.3`, which references `vstfx_exit` — a symbol defined
in the **`ardour` executable**, not in any library. Any out-of-process load
test dies there before reaching our code.

The equivalent check that does work is static. Take the module's undefined
symbols, take the defined symbols of everything the real process maps (the
`ardour` executable plus every in-tree `.so` plus the executable's `ldd`
closure), strip `@VERSION` suffixes from both sides, and diff. Everything
resolves except `__gmon_start__` and `_ITM_{de,}registerTMCloneTable`, which
are weak toolchain stubs left unresolved in every shared object on the system,
maschine2's included.

Worth knowing: the module's `udev_*` undefined symbols come from the in-tree
hidapi being a **static** library, so its libudev dependency lands on us
without a `NEEDED libudev` entry of our own. They resolve only because the host
process already maps libudev. maschine2 is in exactly the same position, so
this is the established in-tree pattern rather than something to fix.

---

## Scope decision — one module for A25 / A49 / A61

**These are one device with three keybeds, and the keybed is not ours.** Knobs,
buttons, encoder and display all arrive over HID; the keys leave over the
device's own MIDI port and never touch the surface. So the entire per-model
difference is a name and a key count — a table, not a class hierarchy.

Evidence:

| Claim | Source |
|---|---|
| PIDs `17cc:1730` (A25), `1740` (A49), `1750` (A61) — +0x10 per size, same pattern as S-series MK1 | `lsusb -v` dumps in [linuxhw/LsUSB](https://github.com/linuxhw/LsUSB); komplementary-kontrol `komplement.c:167` |
| *"Beyond the keybed, all keyboards come with identical features"* | [NI A-Series Manual 2.1.3](https://www.native-instruments.com/fileadmin/ni_media/downloads/manuals/komplete_kontrol/KOMPLETE_KONTROL_A-Series_2.1.3_Manual_English_0619.pdf) §6 p.28 |
| A49 HID descriptor is **502 bytes** — identical to our A61; same 4 interfaces, same endpoints | A49 `lsusb -v` dump |
| Depth and height identical across all three; only width and weight scale | [NI specifications page](https://www.native-instruments.com/en/products/komplete/keyboards/komplete-kontrol-a25-a49-a61/specifications/) |
| komplementary-kontrol, built against an **A25**: 30-byte input report, `0x80` + 21 LED bytes, 40 named buttons | its `komplement.c`, `button_leds.c`, `button_names.c` |

Every A25 number above is an exact match to our A61 map.

**The one real gap:** no public `lsusb -v` for an A25 exists, so its 502-byte
descriptor is inferred, not measured. The module therefore probes all three
PIDs but checks `hid_get_report_descriptor()` on the untested models and warns
loudly on mismatch — the first A25 user produces a bug report rather than a
silent misdecode. There is no A-series MK2; MK2/MK3 are S-series only.

### The M32 is the same family but not the same device

`17cc:1860`. Two projects have captured it, and both corroborate our map:

- [`isovector/free-m32`](https://github.com/isovector/free-m32) decodes its
  buttons with the same `byte = idx/8, bit = idx%8` scheme and its `RawButton`
  enum is **bit-for-bit identical to ours for all 40 bits** — including knob 8
  touch at bit 32 and 4-D press at bit 33, the two controls upstream's
  32-bit-packing A25 code cannot reach.
- [`arfipod/pocket_synth`](https://github.com/arfipod/pocket_synth/blob/main/docs/komplete-m32-oled.md)
  documents the display and reproduces our `0xe0` findings exactly, headers
  included: `E0 00 00 00 00 80 00 02 00` and `E0 00 00 02 00 80 00 02 00` are
  precisely the two full-width 2-page bands we settled on.

But it differs where it matters: **526-byte descriptor** (vs 502), and a
different analog block — touch strips instead of pitch/mod wheels, encoder at
`payload[23]` not `[27]`, and a `keyshift` field at `[36]`, past the end of our
29-byte payload. It also has no known equivalent of `a0 03 04`; pocket_synth
found no takeover command and repaints every ~80 ms to fight the firmware.

**So: leave a variant seam, do not claim support.** The `KKA::Variant` table is
where an M32 would land, but it needs a second input-report decoder and someone
with the hardware.

### Precedent for the table-not-hierarchy choice

`cabl` uses a template parameter (`KompleteKontrol<NKEYS>`); KompleteSynthesia
uses a PID→`{keys, generation}` dictionary; DrivenByMoss uses parallel arrays.
Only Ardour's own `maschine2` splits into subclasses — and that is justified
there, because Mikro/MK2 have genuinely different bit-packed structs, LED bank
sizes and image buffers. Ours do not.

---

## What was built

Branch `komplete-kontrol-a` in the **sibling Ardour checkout**
(`~/projects/ardour`), not in this repo.

```
libs/surfaces/komplete_kontrol_a/
  wscript
  kka_protocol.h        the Phase 1 map as constants -- the transplant
  kka_protocol.cc       variant table + control names
  komplete_kontrol_a.h  ControlProtocol subclass
  komplete_kontrol_a.cc hidapi lifecycle, mode switch, decode, trace
  interface.cc          ControlProtocolDescriptor + factory
```

Four integration points, matching what commit `cac849fe6d` (the launchkey_4
addition) touched:

| File | Change |
|---|---|
| `libs/surfaces/wscript` | `children += ['komplete_kontrol_a']` under `HAVE_HIDAPI` **and** `bld.recurse(...)` in `build()` — both are required, they are separate lists |
| `gtk2_ardour/ardev_common.sh.in` | appended to `ARDOUR_SURFACES_PATH`, or a dev build never finds the `.so` |
| `libs/ardour/ardour/debug.h` | `extern DebugBits KompleteKontrolA;` |
| `libs/ardour/debug.cc` | `new_debug_bit ("kompletekontrola")` |

**Builds by default** whenever `HAVE_HIDAPI` is set — deliberately *not* behind
an opt-in flag like maschine2's `--maschine`. The USB surfaces build
automatically and there is no reason this one should not.

### Naming, and why it is now fixed

Directory `komplete_kontrol_a`, `.so` `libardour_komplete_kontrol_a.so`, class
`KompleteKontrolA`, protocol namespace `KKA`, surface name
**"NI Komplete Kontrol A-Series"**, id `uri://ardour.org/surfaces/komplete_kontrol_a:0`.

The descriptor `name` is the key used in session and config XML, so it must
stay stable forever — renaming it later breaks every user's saved surface
selection. It names the family rather than the A61 precisely so that adding
A25/A49 never requires a rename.

### Behaviour

- `available()` = `hid_init()` round-trip only. It must **not** check for a
  present device: returning false makes Ardour unload the module permanently,
  so a user who plugs in later would never get it back.
- `start()` probes the three PIDs widest-first, enters interactive mode
  (`a0 03 04`), clears LEDs, blanks the panel, then attaches a 1 ms
  `Glib::TimeoutSource` read poll to the `AbstractUI` context (maschine2's
  pattern). Reports are on-change-only, so this is a "did anything happen"
  poll, not a sample clock.
- `dev_read()` drains up to 32 reports per tick rather than one — a fast knob
  spin coalesces several between wakeups.
- The **first** report seeds state without emitting events. The device reports
  on change only, so whatever position it is sitting in at startup must not
  read as a burst of user input.
- `stop()` clears LEDs, blanks the display, restores MIDI mode, closes.
  Blanking is not cosmetic: once interactive mode is entered the firmware stops
  drawing the panel and **never resumes**, so quitting without blanking strands
  our last frame on the screen until the user replugs.

Decode follows `docs/a61-hid-map.md` exactly: 40-bit button field over
`payload[0:5]` (bits 34–39 padding, not dispatched), 8 × u16 LE knobs at
`[5:21]` as wrapping counters at 8 units/detent with a **remainder-carrying
accumulator**, 4-bit wrapping encoder in the low nibble of `[27]`.

---

## Next — Phase 3

1. **Verify the scaffold on hardware.** The build is done; this is the next
   action. Needs a display, so it has to be run from Josh's desktop session:

   ```sh
   cd ~/projects/ardour
   ARDOUR_DEBUG_FLAGS=kompletekontrola,controlprotocols ./dev ./gtk2_ardour/ardev
   ```

   **Two traps here cost three wasted runs, so get them right first.** The
   variable is `ARDOUR_DEBUG_FLAGS`, *not* `ARDOUR_DEBUG` — the bare name is
   read by nothing in the tree (`gtk2_ardour/main.cc:181`), so it fails
   silently and every trace stays off. Confirm it landed: `parse_debug_options`
   prints `Debug flag '<name>' set` to stdout for each flag it matches, so if
   those lines are absent, nothing downstream means anything.

   And **`PBD::info`/`warning`/`error` do not reach the terminal once the GUI
   is up.** `UI::receive` (`libs/gtkmm2ext/gtk_ui.cc:579`) captures them into
   the Log window; only pre-GUI messages hit stderr. Every message this module
   emits from `open_device()` lands in **Window → Log**. `DEBUG_TRACE` is the
   exception and goes to stderr. A silent terminal is therefore not evidence of
   anything — check both.

   Then enable **NI Komplete Kontrol A-Series** in Preferences → Control
   Surfaces and confirm every control traces. Two things already check out:
   `build/gtk2_ardour/ardev_common_waf.sh` has the surface directory on
   `ARDOUR_SURFACES_PATH`, and the A61 enumerates as `17cc:1750` — the first
   entry in `KKA::Variants`, so `open_device()` should match on its first
   probe. Remember Josh drives the hardware: hold static states and let him
   describe them rather than sweeping.

   Expect the surface to appear as three rows (A25/A49/A61) under a "Native
   Instruments" parent, not as one row named after the module. That is how
   `enumerate()` feeds the GUI (`gtk2_ardour/rc_option_editor.cc:1617`), and
   the picked name lands in `cpi->config`, which the factory ignores. In-tree
   `contourdesign` behaves identically with its three ShuttlePRO variants, so
   this is the precedent, not a defect. Ticking any one of the three loads the
   module, which then probes for whatever is actually plugged in.
2. **Hotplug.** Interactive mode does not survive a replug and the device comes
   back silently sending CC 14–21 at the user's tracks. The surface currently
   asserts the mode once at `start()`. Needs re-assertion on reconnect.
3. Bind knobs to the selected strip via `Stripable` / `PresentationInfo`;
   buttons to transport, banking, Undo/Redo, Metro, Mute/Solo; 4-D rotation to
   jog. Shift works as a modifier **only** in interactive mode — the firmware
   swallows bit 0 in MIDI mode.
4. **No shadow port, no `AsyncMIDIPort`, no realtime filter.** Phase 1 killed
   that whole branch: with knobs off MIDI, the device's port is already a plain
   music port. See the Phase 1 doc's "Consequences for the build".

Phase 4 is LEDs (index == button bit index, no mapping table); Phase 5 is the
font and the touched-knob display.

---

## Corrections this research forces on `docs/a61-hid-map.md`

Not yet applied — worth doing before the doc goes anywhere public:

1. **Inverted polarity is no longer unique to us.** The doc says it "is **not**
   predicted by any upstream source." pocket_synth independently documents it
   on the M32 (`setM32OledOutputInverted(true)`). Soften to: not predicted by
   *cabl or DrivenByMoss*, but independently corroborated on sibling hardware.
   The mixed pixel/page header units are likewise corroborated.
2. **Upstream's real limit is 21, not 32.** The doc says komplementary-kontrol's
   32-bit packing hides bits 32–33. True, but its dispatch loop is
   `for (button_number = 1; button_number < TOTAL_HID_BUTTONS; ...)` with
   `TOTAL_HID_BUTTONS == 21` — the LED count reused as a button bound. So it
   only ever handles bits 1–20, and its silence on the 4-D directions and all
   eight touch sensors is *not* evidence the A25 lacks them. It never looked.
3. **Bits 22/23 conflict with upstream.** It names 22 "4D Right" and 23
   "4D Left"; we have them swapped. Since it never dispatched those bits, ours
   is empirical and theirs is almost certainly an untested guess — but the
   disagreement should be recorded.
4. **A free hypothesis for open question 2.** `payload[28]`, constant 36 in
   every capture: free-m32 names its equivalent M32 field `keyshift`, and our
   keys are notes 36–96. So it is plausibly the base note / octave-shift value.
   One press of Octave Up would settle it.
5. **The A61's family/member sysex reply is still the only one published.**
   Searches for any A25/A49/M32 Universal Identity Reply found nothing, so the
   doc's `0x19`/`0x31` conjecture for A25/A49 remains pure speculation and
   should stay marked as such. Corroborating detail worth adding: `0x1730` is
   simultaneously the A-series *sysex family code* and the *A25's USB PID*,
   consistent with the family being named after the base model — and
   komplementary-kontrol's A25-derived sysex lead-in carries the same `30 17`.
