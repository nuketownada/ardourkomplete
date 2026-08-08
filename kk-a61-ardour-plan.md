# Komplete Kontrol A61 → Ardour on Linux/NixOS

Handoff document for Claude Code.

**Target architecture:** an in-tree Ardour control surface module that reads the
A61's buttons, 4-D encoder and touch sensors over USB **HID**, and takes the
device's USB-MIDI port as its own surface input — consuming the knob and mod
CCs as control data while passing keys, pitch bend and pressure through to a
shadow port that feeds MIDI tracks.

**Route to get there:** reverse-engineer the HID protocol first with a small
standalone C tool where the iteration loop is seconds, not minutes. Decision
gate at the end of Phase 1. Do not start writing C++ against Ardour internals
until the device's HID reports are fully decoded on *this* hardware.

Everything under "Established facts" is verified. Items marked **ASSUMPTION**
are not — test before building on them.

---

## Established facts

### What the A61 sends over USB-MIDI (verified by `aseqdump` on this unit)

| Control | Message |
|---|---|
| Knobs 1–8 | CC 14–21, channel 1, **absolute**, ±1 per detent, no acceleration, clamps 0/127 |
| Mod wheel | CC 1 |
| Pitch wheel | standard 14-bit, returns to 0 |
| Keys | notes 36–96, note-on velocity + release velocity |
| Knob touch sensors | **nothing** |
| Play / Stop / Rec / Loop | **nothing** |
| 4-D encoder (rotate, tilt, press) | **nothing** |
| All other buttons | **nothing** |

Transport and the 4-D encoder are USB **HID**, not MIDI. On Windows/macOS NI's
host-integration daemon reads HID and republishes it on a virtual "DAW" MIDI
port; that daemon has no Linux equivalent, so those controls are inert. Online
captures showing KK transport buttons emitting notes 86–99 were taken on
Windows with NI drivers loaded — those note numbers are an artefact of the
daemon, not the hardware.

Single MIDI port: keys and knobs share it. That is why the shadow-port filter
below matters.

### Reference source A: `hugovangalen/komplementary-kontrol`

GPL-3.0, archived 2023-06-15, 28 commits, developed against an **A25**. This is
the only known source of A-series HID knowledge.

- **`hid.c/.h`** — hidapi wrapper: `hidstuff_init(vid,pid)`,
  `hidstuff_read_raw_timeout()`, `hidstuff_send_raw()`. Bidirectional.
- **`komplement.c`** (532 lines) — main loop. Reads HID with 2000 ms timeout,
  packs `keypress_buffer[1..4]` into a 32-bit button bitfield, bit 0 = Shift,
  handles the 4-D encoder separately via a dial-position byte at
  `keypress_buffer[28]`. Has commented-out `printf("%08b ")` raw tracing around
  line 389 — re-enable this in Phase 1.
- **`button_names.c`** — full control inventory: Shift, Scale, Arp, Undo,
  Quantize, Ideas, Loop, Metro, Tempo, Play, Record, Stop, Preset Up/Down,
  Mute, Solo, Browser, Plug-In, Track, Octave Down/Up, 4D Up/Right/Left/Down,
  4D Button, **Rotary1–8**, Button34–39, plus pseudo-buttons `4D CW` / `4D CCW`.
  `Rotary1–8` are the **touch sensors** — invisible over MIDI, present in HID.
- **`button_leds.c`** — HID report `0x80` + 21 LED bytes.
  `LED_OFF 0x00`, `LED_ON 0x7c`, `LED_BRIGHT 0x7e`.
- **`konfigure.c`** — sysex to reconfigure the rotaries. Lead-in
  `f0 00 21 09 30 17 4d 43 01 00 01 0a 04` (`00 21 09` = NI manufacturer ID),
  separate `PEDAL_LEAD_IN` packet, presets hold 4 pages × 8 knobs. Contains,
  in a dead `#ifdef HARDCODED_ASSIGNEMENTS` block:
  `buffer[3] = 0x00; // 0x00 = ABS, 0x01 = REL, 0x01 REL OFFSET` with REL
  OFFSET using `0x3f`/`0x41`.

Author's own warnings: his OLED was garbled on two separate units, and the
second knob label on every preset page comes back corrupted regardless of
correct data being sent. Treat OLED labelling as unreliable; don't sink time
into it.

### Reference source B: Ardour's existing surfaces

`libs/surfaces/` contains three non-MIDI-transport modules, all gated in
`libs/surfaces/wscript` on libusb-1.0:

- **`contourdesign`** — ShuttlePro, pure HID. Smallest, cleanest example.
- **`push2`** — HID + USB bulk display, and the source of the shadow-port
  pattern described below.
- **`maschine2`** — **a Native Instruments device via hidapi**, ~4000 lines
  covering three hardware variants. `M2Device` is a pure-virtual interface
  whose entire surface is `read(hid_device*, M2Contols*)`,
  `write(hid_device*, M2Contols*)` and `surface()` returning a Cairo image
  surface. `maschine2.h` holds both `hid_device* _handle` and a
  `std::shared_ptr<ARDOUR::Port> _midi_out` — the hybrid model, already in tree.

**This is the template.** An A61 module is a fraction of maschine2's scope: 8
knobs, ~21 LEDs, one small OLED, no pads, no RGB grid.

### The shadow-port mechanism (this is how the CC-capture requirement is met)

`AsyncMIDIPort` supports a shadow port plus a realtime input filter.
`Push2::pad_filter(MidiBuffer& in, MidiBuffer& out)` inspects every incoming
event: pad notes are consumed and translated as control, while pitch bend,
poly pressure and channel pressure are pushed to `out` and thus to the shadow
port, which is what connects to a MIDI track. `Push2::stripable_selection_changed()`
re-points the shadow port at whichever `MidiTrack` is currently selected.

The A61 equivalent — call it `a61_filter` — consumes CC 14–21 (and optionally
CC 1) as surface control, and forwards notes, pitch bend and channel pressure
to the shadow port. Make the mod-wheel disposition configurable
(consume / forward / both); it is genuinely useful as performance data to
instruments, and swallowing it unconditionally would be a regression.

The source comment states the filter runs asynchronously from a realtime
process context: **no locks, no allocation, atomics only for state.**

**Contingent on the Phase 1 mode experiment.** If the device can be put into
"Interactive Mode" over HID such that the knobs stop emitting CC while the keys
keep emitting notes, this filter has little left to consume and the surface
input port may be unnecessary — the A61's MIDI port would then connect straight
to tracks as a plain music port. Settle that question before writing the filter.

---

## Phase 0 — Nix build environments

Two separate environments; set both up before touching code.

1. **Discovery tool:** a flake devShell with `hidapi`, `alsa-lib`,
   `pkg-config`, `gcc`, `gnumake`.
2. **Ardour:** do *not* iterate via `overrideAttrs` — a full derivation rebuild
   per edit is unusable. Use `nix develop nixpkgs#ardour` to get the dependency
   closure, then run waf against a git checkout of the Ardour source normally,
   for incremental compiles. Reserve `overrideAttrs` (with `src` pointed at the
   fork) for producing a reproducible install once the module works.
3. **Device permissions:** NixOS `services.udev.extraRules` granting the user's
   group read/write on the A61's USB device. Upstream ships
   `udev/55-komplete-kontrol.rules` as a starting point; it targets group
   `audio`.
4. Confirm the A61's VID/PID via `lsusb` and check it against what
   `hidstuff_init` is called with. **The upstream code targets an A25** — if the
   PID differs, that is the first patch and everything downstream depends on it.

**Exit criterion:** both shells build; `lsusb` shows the device; the udev rule
grants access without root.

---

## Phase 1 — Protocol discovery (standalone tool)

Fork komplementary-kontrol and use it as a reverse-engineering rig, not as a
product. Goal is a complete, verified decode of *this* A61's HID reports.

1. Build it, re-enable the raw-byte tracing near `komplement.c:389`, and dump
   HID reports while pressing every control.
2. Produce a written report map: which byte/bit corresponds to each of the ~34
   buttons, the Shift bit, the 4-D tilt directions, the 4-D press, the encoder
   delta byte, and each of the 8 touch sensors. Record it as a table in the
   repo — this artefact is the deliverable of the phase and it is what gets
   transplanted into C++ later.
3. Verify the LED write path: `0x80` + 21 bytes, three brightness levels.
   Confirm the index→button ordering on the A61, which has more controls than
   the A25 and may not match.
4. Determine whether the knobs' *rotation values* appear in HID at all, or only
   over MIDI. **ASSUMPTION:** rotation is MIDI-only and HID carries just the
   touch state. If rotation turns out to be in HID too, the shadow-port filter
   gets simpler.
5. **Mode-switch experiment — do this before designing Phase 3.**
   `komplement.c:271` sends `a0 07 00` over HID at startup, documented as
   resetting the device to "MIDI Mode". Immediately above it, commented out,
   is `a0 03 04`, documented as putting the device into a mode where "all the
   normal operation ceases and it interfaces with the operating system"
   ("Interactive Mode"). Upstream never shipped this — it is observed, not
   tested.

   **Before sending `a0 03 04`, have a one-line script ready that sends
   `a0 07 00`.** A-series keyboards are known for getting stuck in a mode, and
   on Linux there is no NI software to recover them.

   Send `a0 03 04`, then determine with `aseqdump`:
   - **Watch the OLED first — it is a free mode indicator.** In MIDI mode the
     firmware owns the display and renders CC readouts ("CC 21 64") as knobs
     move. If those readouts stop, the firmware has relinquished the screen and
     the mode switch took effect. This is faster and clearer than any MIDI
     observation.
   - Do the knobs stop emitting CC 14–21? (The desired outcome.)
   - Does the mod wheel stop emitting CC 1?
   - **Do the keys still emit notes over MIDI?** This is the load-bearing
     question.
   - If keys go silent, does HID now carry key events — with velocity,
     release velocity, pitch bend and aftertouch?

   Outcomes:
   - *Knobs silent, keys still MIDI* → best case. Phase 3's filter has little
     or nothing to consume; the surface reads all control data over HID and
     the MIDI port stays a plain music port.
   - *Everything silent, HID carries keys* → full-HID architecture is possible
     but materially larger: note synthesis, velocity curves and pitch/mod
     handling all move into the module. Scope this deliberately, don't drift
     into it.
   - *Everything silent, HID does not carry keys* → interactive mode is a trap.
     Stay in MIDI mode and use the shadow-port filter as planned.

6. Optional but cheap — test the relative-rotary sysex. Copy
   `presets/basic_cc.pst`, change one knob to `Jog,0,0,7,1,63,65`, send with
   `konfigure` + `amidi`, and watch `aseqdump` for 1/65 deltas instead of an
   absolute ramp. **ASSUMPTION:** the `.pst` trailing fields map to
   `data[0]`=CC, `data[1]`=ABS/REL, `data[2..3]`=range or step. If the ramp
   doesn't change, instrument the `wrap_fwrite(button.data, 4)` call and bisect
   against the ABS/REL/REL-OFFSET comments.
   *Risk:* this writes device config over sysex. It's the documented preset
   mechanism rather than a firmware flash, but the protocol is reverse-engineered
   against different hardware. Capture current state first if it can be read back.

**Exit criterion:** every physical control decoded and documented; LEDs
individually addressable.

### Decision gate

- **Clean decode, A25 assumptions largely held** → proceed to Phase 2. The C++
  work is then mostly mechanical transplant.
- **Substantial divergence, still reverse-engineering** → stay in the standalone
  tool until the map is complete. Do not debug protocol questions inside a waf
  build.

---

## Phase 2 — Ardour surface module skeleton

1. Fork Ardour. New directory `libs/surfaces/kontrol_a61/`, modelled on
   `contourdesign` for structure and `maschine2` for the hidapi device
   abstraction.
2. Register it in `libs/surfaces/wscript` alongside the other libusb-gated
   modules.
3. Implement `interface.cc` (the module entry points), a `KontrolA61` protocol
   class holding `hid_device* _handle`, and a device-read thread that translates
   HID reports into internal button/encoder events using the Phase 1 map.
4. No Ardour bindings yet — just log decoded events. Confirm the module loads,
   appears in Preferences → Control Surfaces, and sees the device.

**Exit criterion:** module loads in a locally-built Ardour and logs every
control press.

---

## Phase 3 — Control bindings and the shadow-port filter

1. Request an `AsyncMIDIPort` for the surface input, install `a61_filter`, and
   set up the shadow port. Follow `Push2::pad_filter` and
   `Push2::stripable_selection_changed` closely — including the realtime
   constraints.
2. Filter policy: consume CC 14–21; forward notes / pitch bend / channel
   pressure; mod wheel (CC 1) configurable.
3. Bind knobs to the selected strip (gain, pan, sends, plugin params) via
   `Stripable` / `PresentationInfo`. Implement pickup/soft-takeover directly —
   you have the real target value, so this is better than anything the generic
   MIDI layer can do, and it makes the Phase 1 relative-rotary work optional.
4. Bind buttons: transport, banking on 4-D left/right, track selection on
   4-D up/down, Undo/Redo, Metro, Mute/Solo on selection. Shift as a modifier
   for a second layer.
5. 4-D rotation → playhead scrub / jog.

**Exit criterion:** knobs and buttons drive Ardour; keys still reach the
selected MIDI track through the shadow port.

---

## Phase 4 — LED feedback

Connect Ardour state to the lights. Unlike the MIDI-daemon approach, this needs
no round-trip: subscribe to `PBD::Signal` notifications on transport state,
rec-arm, mute/solo and selection, and drive `0x80` LED writes from the
callbacks. Mind the threading boundary between signal callbacks and the HID
write path.

---

## Phase 5 — Touch sensors and OLED

1. `Rotary1–8` touch events → Ardour's touch-mode automation, so grabbing a
   knob arms writing. Highest value per line of code once everything else works.
2. **OLED — conditional on interactive mode.** There are two entirely separate
   display paths, and upstream only ever touched the first:

   - *Firmware-rendered (MIDI mode).* The device draws the screen itself,
     showing CC readouts as knobs move. Text can be pushed only as preset
     labels via the `konfigure` sysex mechanism, and upstream reports the
     second label on every page comes back garbled. Dead end for showing
     Ardour state.
   - *Host-rendered (interactive mode).* The host owns the display. This is
     what NI's own software uses to show track and parameter names, and it is
     the only path that can render live Ardour state — the actual parameter
     name and value under the knob you just touched.

   Upstream contains **no display-write code at all**, so the host-rendered
   protocol is unmapped. `maschine2` renders to a Cairo `ImageSurface` and
   pushes it over hidapi; `push2` uses USB bulk transfer for a larger screen.
   One of those shapes likely fits the A61's small mono panel, but expect to
   establish the report format from scratch.

   If Phase 1 shows interactive mode is unreachable, host-driven display is not
   merely difficult — it is impossible, and the project's honest scope is
   buttons, LEDs and knobs.

---

## Notes

- Ardour's control-protocol API carries no stability guarantee; expect to rebase
  the fork. Upstreaming is the long-term fix and there is clear precedent for
  accepting NI HID surfaces (maschine2).
- komplementary-kontrol is GPL-3.0; Ardour is GPL-2.0-or-later. Lifting code
  verbatim from the former into the latter is a licence problem — **port the
  documented protocol knowledge from Phase 1, not the source.** This is another
  reason Phase 1's output should be a written report map rather than a patch.
- Keep the standalone tool in the repo after Phase 1. It stays the fastest way
  to test protocol questions without a waf rebuild.
