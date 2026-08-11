# Komplete Kontrol A61 — HID report map

Phase 1 deliverable. This is the artefact that gets transplanted into C++.

**Unit under test:** A61, firmware build dated 2022-01-05, USB `17cc:1750`.
(Per-unit serial and unit ID are redacted throughout — their *report layouts*
are documented below, which is the reusable part. The hidraw node number is not
stable across replugs; match on VID/PID.)

**Provenance.** Everything here is derived from (a) the device's own HID report
descriptor and feature reports, and (b) our own captures on this unit. No code
or data was taken from `hugovangalen/komplementary-kontrol`. Where that
project's *published findings* are referenced it is for cross-validation only,
and it is called out explicitly. This keeps the GPL-3 → GPL-2 provenance
question moot rather than merely managed.

Status legend: **VERIFIED** = observed on this unit. **ASSUMPTION** = not yet
tested.

---

## Report inventory (from the device's HID report descriptor)

| Report | Dir | Payload | Purpose |
|---|---|---|---|
| `0x01` | Input | 29 B | all controls |
| `0x80` | Output | 21 B, range 0..127 | LEDs |
| `0xa0` | Output | 2 B | mode switch |
| `0xe0` | Output | 8 B header + 256 B | display — **SOLVED**, 128×32 1bpp |
| `0xf4` | Output | 1 B + 31 B | unknown; *not* a text path |
| `0xd0` | Feature | 32 B | device info |
| `0xd8` | Feature | 32 B | device info (const) |
| `0xd9` | Feature | 32 B | serial string (ASCII) |
| `0xf8` | Feature | 10 B | display config |

The descriptor is authoritative for *structure*. It says nothing about which
bit means which physical control — that is what the captures establish.

---

## USB topology — VERIFIED

From sysfs. This bounds what is protocol-discoverable at all, so it is worth
having before theorising about the display.

| Interface | Class | Driver | Endpoints |
|---|---|---|---|
| 0 | `01` Audio (control) | `snd-usb-audio` | none |
| 1 | `01` Audio (MIDIStreaming) | `snd-usb-audio` | Bulk OUT `0x02`, Bulk IN `0x82`, 64 B |
| 2 | `03` HID | `usbhid` | Interrupt OUT `0x01`, IN `0x81`, 64 B |
| 3 | `fe` Application-Specific | — | none |

Three consequences:

1. **Interface 3 is class `0xFE` with zero endpoints — that is a DFU runtime
   descriptor.** Firmware-update mode is one control transfer away. Do not
   sweep command spaces blindly, and do not touch interface 3.
2. **There is no bulk endpoint capable of carrying display data.** The two bulk
   endpoints on interface 1 are USB-MIDI. This rules out the S-series MK2/MK3
   approach — those push framebuffers over dedicated bulk endpoints — and means
   the display, if reachable at all, is reachable *only* through HID interface 2.
3. **The device exposes exactly one MIDI port** (`KOMPLETE KONTROL A61 MIDI 1`,
   ALSA sequencer client `24:0`). There is no second "DAW"/host-integration
   port, so NI's host integration cannot be running over a private MIDI port
   either. Combined with (2), everything the host can say to this device goes
   through HID or through sysex on the single music port.

### The "Komplete Kontrol A DAW" port is virtual — it does not exist in hardware

Worth knowing, because it explains why every DAW-integration project skips
Linux, and why this one does not have to.

On Windows/macOS the A-series exposes a second MIDI port named
`Komplete Kontrol A DAW`. It is **not a USB endpoint** — it is a Bome virtual
MIDI port created by NI's Host Integration Agent (NIHIA). NIHIA claims the USB
device, translates HID↔MIDI, renders display text host-side, and republishes
the result on that virtual port. When it breaks, NIHIA logs
`Unable to connect to BMIDI port 'Komplete Kontrol A DAW': port does not exist`.

Consequences:

- Linux has nothing to expose. This is not a missing driver.
- DAW-integration projects (DrivenByMoss, reaKontrol, FLIN) target that virtual
  port, so they require NIHIA and are Windows/macOS only.
- The virtual port carries **strictly less** than the hardware does — buttons
  arrive latched rather than momentary, knob touch is not exposed at all. Our
  HID map has full press/release for 34 controls and all 8 touch sensors.

**So the right architecture is to bypass NIHIA entirely and own the device over
HID**, which is what DrivenByMoss does for the S-series MK1 — the one model it
supports on Linux, and the one where it gets track names on the display. That
is exactly the path this project takes, now including the panel.

---

## Input report `0x01` — 30 bytes total (1 ID + 29 payload)

Offsets below are into the **payload** (report ID stripped). Upstream indexes
its `keypress_buffer` with the ID included, so `payload[n]` == upstream's
`keypress_buffer[n+1]`.

| Payload | Fields | Range | Meaning | Status |
|---|---|---|---|---|
| `[0:5]` | 40 × 1 bit | 0..1 | buttons + touch sensors | **VERIFIED** |
| `[5:21]` | 8 × u16 LE | 0..999 | knob values — reads `0` in MIDI mode | **VERIFIED silent** |
| `[21:25]` | 2 × u16 LE | 0..4095 | pitch bend, mod wheel — read `0` in MIDI mode | **VERIFIED silent** |
| `[25:27]` | 1 × u16 LE | 0..4095 | third analog, pedal? — reads `0` in MIDI mode | **VERIFIED silent** |
| `[27]` | 2 × u4 | 0..15 | low nibble = 4-D encoder; high nibble unused | **VERIFIED** |
| `[28]` | u8 | 0..127 | **octave base note** — MIDI note of the lowest key, `36` at rest | **VERIFIED** |

The device emits input reports **on change only** — no idle traffic. Confirmed
over a 3 s idle listen and three capture sessions.

### Button bitfield, `payload[0:5]`

Bit index = `byte * 8 + bit`, LSB first.

**Complete map — VERIFIED.** Established by two full ordered passes (one in
each mode) with names supplied by the operator; 26 named controls produced
exactly 26 events in interactive mode, a clean 1:1.

| Bit | Control | Bit | Control |
|---|---|---|---|
| 0 | **Shift** (see note) | 17 | Plug-In |
| 1 | Scale | 18 | Track |
| 2 | Arp | 19 | Octave Down |
| 3 | Undo | 20 | Octave Up |
| 4 | Quantize | 21 | 4-D Up |
| 5 | Ideas | 22 | 4-D Left |
| 6 | Loop | 23 | 4-D Right |
| 7 | Metro | 24 | 4-D Down |
| 8 | Tempo | 25–32 | Knob 1–8 touch |
| 9 | Play | 33 | **4-D Press** |
| 10 | Rec | 34–39 | unused |
| 11 | Stop | | |
| 12 | Preset Up | | |
| 13 | Preset Down | | |
| 14 | M / Page Left | | |
| 15 | S / Page Right | | |
| 16 | Browser | | |

That is 34 controls in 40 declared bits, with 34–39 unused padding.

### Shift is swallowed by the firmware in MIDI mode — VERIFIED

Bit 0 (Shift) does **not** appear over HID in MIDI mode. The identical ordered
pass produced bits 1–18 in MIDI mode and bits 0–18 in interactive mode; every
other control reported identically in both. The firmware evidently reserves
Shift as its own modifier while it owns the panel.

Practical consequence: **a MIDI-mode-only surface cannot use Shift**, which
removes the second layer the plan wanted it for. This is another point in
favour of running in interactive mode.

For the record, the page buttons (M / S, bits 14 / 15) report normally in
*both* modes despite also driving the firmware's overlay pages, and bits 19/20
were never "missing" — they are Octave Down/Up and simply had not been pressed.

**Touch-sensor ordering — VERIFIED left-to-right:**

| Knob | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| Bit | 25 | 26 | 27 | 28 | 29 | 30 | 31 | 32 |
| Byte.bit | 3.1 | 3.2 | 3.3 | 3.4 | 3.5 | 3.6 | 3.7 | 4.0 |

Established by two independent captures: one tapping each knob 2–3 times in
succession (clean ascending sweep across exactly these eight bits), and one
touching only the leftmost knob, pausing, then only the rightmost — which
produced bit 25 then bit 32, fixing the direction.

> **Consequence for anyone porting upstream's approach:** `komplement.c` packs
> `keypress_buffer[1..4]` into a 32-bit field — bits 0..31 only. The A61
> descriptor declares **40** button bits. Two real controls live past that
> window: **knob 8's touch sensor (bit 32)** and the **4-D encoder press
> (bit 33)**. Code built on the A25's 32-bit assumption cannot see either.

### 4-D encoder, `payload[27]` low nibble

A 4-bit **wrapping absolute position counter**, not a delta. Increments by 1
per detent clockwise, decrements counter-clockwise, and wraps cleanly
`15 → 0` and `0 → 15`. **VERIFIED** across ~60 detents in both directions.

Signed delta:

```c
int d = ((cur - prev + 8) & 0x0F) - 8;
```

Cross-validation: upstream documents its dial-position byte at
`keypress_buffer[28]`, which is `payload[27]` — an exact match, and evidence
that A25 knowledge transfers to the A61 for this field.

The **high** nibble of `payload[27]` never changed in any capture.

---

## Modes — `a0 03 04` WORKS on the A61

**VERIFIED.** Interactive mode engages on this unit and produces the outcome
the project plan named as its best case: *knobs go silent on MIDI and appear
in HID, while keys keep emitting MIDI notes.*

| Control | MIDI mode | Interactive mode |
|---|---|---|
| Buttons, touch sensors, 4-D encoder | HID | HID (unchanged) |
| **Knob rotation** | **MIDI, CC 14–21, absolute 7-bit, clamps** | **HID `payload[5:21]`, endless/wrapping** |
| Keys | MIDI notes 36–96, velocity + release velocity | **MIDI, unchanged** |
| Pitch bend | MIDI, 14-bit | **MIDI, unchanged** |
| Mod wheel | MIDI, CC 1 | **MIDI, unchanged** |
| `pb`/`mod`/`aux` HID fields | `0` | still `0` |

Verified by simultaneous capture: `aseqdump` recorded 119 Control-change
events, **all of them controller 1 (mod wheel)** and not one CC 14–21, plus
normal note on/off with release velocity and full 14-bit pitch bend — while
HID showed all eight knob fields active.

The declared `pb`, `mod` and `aux` fields at `payload[21:27]` stay `0` in
**both** modes. They are probably provisioned for a different model in the
family. Do not plan around them.

### Knob encoding in interactive mode — endless, not absolute

Each knob is a **wrapping counter moving 8 units per step**, over the declared
0..999 range. It does *not* clamp.

**"Step" is the reporting quantum, not a detent.** The knobs rotate freely with
no mechanical click; nothing here is something the player can feel. Earlier
revisions of this document called it a detent, which asserted a physical
property this hardware does not have.

Observed transitions:

```
turning down:   8 -> 0 -> 991 -> 983      (0 - 8 wraps to 991)
turning up:   999 -> 8                    (999 + 8 wraps to 8)
```

Deltas of ±8, ±16 and ±24 appear when reports coalesce during a fast spin, so
never assume one step per report. Signed delta, wrap-safe:

```c
int raw = cur - prev;
if (raw >  500) raw -= 999;
if (raw < -500) raw += 999;
int steps = raw / 8;          /* signed; may be several per report */
```

Optional hardening: `raw / 8` truncates toward zero, so any `raw` not on the
8-grid silently loses its remainder. **Every delta observed on this unit is an
exact multiple of 8**, so this is exact today — but a dropped report or a
partial firmware step would discard the fractional part rather than carry it.
One line makes it robust against a case we have not seen:

```c
acc[k] += raw;                  /* per-knob accumulator, persists */
int steps = acc[k] / 8;
acc[k] -= steps * 8;          /* keep the remainder for next time */
```

**This is the single most useful consequence of interactive mode.** Endless
relative encoders have no soft-takeover problem by construction — there is no
value discontinuity to reconcile when the bound parameter changes. Note it is
*not* a resolution win: 999 / 8 ≈ 125 steps per revolution-equivalent, which
is essentially the same granularity as the 7-bit CC. The win is **relative
instead of absolute**, and getting the knobs off the MIDI port entirely.

### Consequences for the build

1. **The shadow-port filter is unnecessary — delete it from the plan.** With
   knobs off MIDI, the A61's MIDI port carries only keys, pitch bend and mod
   wheel: it is already exactly a plain music port and can connect straight to
   a MIDI track. No `AsyncMIDIPort`, no realtime input filter, no shadow port,
   no re-pointing on selection change. This removes the most delicate part of
   the project — the part carrying "no locks, no allocation, atomics only for
   state" realtime constraints.
2. **The mod wheel disposition question dissolves.** The plan wanted
   consume/forward/both configurable so that swallowing CC 1 would not be a
   regression. It is now forwarded natively, with no code and no setting.
3. **The sysex relative-rotary reconfiguration is dead.** Its entire purpose
   was to convert the absolute knob ramp into relative deltas. Interactive
   mode does that for free, so the one step that would have written persistent
   config over a protocol reverse-engineered against different hardware can be
   dropped outright.
4. **Soft-takeover/pickup is no longer needed** for knobs (see above).

---

## Output report `0x80` — LEDs

21 bytes, each declared range **0..127**. Matches upstream's report ID and
byte count exactly (cross-validation that this transfers from the A25).

Upstream's published constants are `LED_OFF 0x00`, `LED_ON 0x7c`,
`LED_BRIGHT 0x7e`. Note the descriptor declares a full 0..127 range, so
brightness is plausibly a **continuum** rather than three discrete levels.
**ASSUMPTION** — the continuum is untested; only 0x00 and 0x7e have been used.

### LED index == button bit index — VERIFIED

A full 21-index sweep (`tools/a61led.py sweep`) was observed on the panel. The
order is *exactly* the button bitfield order:

| LED / bit | Button | LED / bit | Button |
|---|---|---|---|
| 0 | Shift | 11 | Stop |
| 1 | Scale | 12 | Preset Up |
| 2 | Arp | 13 | Preset Down |
| 3 | Undo | 14 | M (Page Left) |
| 4 | Quantize | 15 | S (Page Right) |
| 5 | Ideas | 16 | Browser |
| 6 | Loop | 17 | Plug-In |
| 7 | Metro | 18 | Track |
| 8 | Tempo | 19 | Octave Down |
| 9 | Play | 20 | Octave Up |
| 10 | Rec | | |

**There is no mapping table to write.** For any control with an LED,
`led_payload[i]` drives the button whose input bit is `i`. Bits 21–24 (4-D
directions), 25–32 (knob touch) and 33 (4-D press) have no LED, which matches
the physical panel — the 4-D encoder and the eight knobs are unlit.

This also means a driver can carry a single 34-bit control enum and index both
directions off it, with `i < 21` as the has-LED predicate.

---

## Output report `0xa0` — mode switch

2 payload bytes, matching the 3-byte sequences (ID + 2) documented by
upstream:

| Bytes | Mode | Status |
|---|---|---|
| `a0 07 00` | MIDI mode (default) | upstream-tested |
| `a0 03 04` | Interactive mode | **VERIFIED working on this A61** |

### Mode does not persist across a power cycle — VERIFIED

After unplugging and replugging the device it comes back in **MIDI mode**:
the screen is live again, knobs show CC readouts and the overlay pages
respond.

**Requirement for the Ardour module:** send `a0 03 04` when the surface starts
and `a0 07 00` when it shuts down or is disabled. Do not assume the device is
in the mode you left it in — read a knob or check for CC traffic if
confirmation is needed. This is a hard design constraint, not a nicety: a user
who replugs mid-session gets a device that has silently reverted to sending CC
14–21 on the music port.

**Recovery**, from any shell, no dependencies:

```sh
printf '\xa0\x07\x00' > /dev/hidrawN
```

Or `tools/a61mode.py midi`. Power-cycling the USB connection is the backstop.

`N` is not stable — it changes across replugs. Match on VID/PID rather than
hard-coding it; walk `/sys/class/hidraw/*/device/../..` and compare `idVendor`
/ `idProduct` against `17cc` / `1750`.

---

## Display

**Geometry 128 × 32**, from feature report `0xf8`: usage `0xe1` = `0x0080`
(128), usage `0xe2` = `0x0020` (32). **VERIFIED read**, semantics are a strong
inference from the values themselves.

Corroborated by the *runtime* contents of `0xf8`, which are distinct evidence
from the descriptor's logical maxima — the descriptor says the field *can* hold
128/32, the read says it *does*:

```
0xf8 payload: 80 00 20 00 01 00 00 00 64 00
              ^^^^^ ^^^^^       ^^^^^ ^^^^^
              w=128 h=32        bool  100      (u16 little-endian)
```

That `0xf8` is a read-only capability block also explains its `SET_FEATURE`
STALL without needing to invoke a handshake: you cannot write to a description
of the hardware. This removes what had been the strongest single piece of
evidence for the unlock/handshake theory.

`0xf8` also carries two 0..100 fields (usage `0xe6` reads **100**, usage `0xe7`
reads 0) and a 0..1 boolean. **ASSUMPTION:** `0xe6` is brightness percent.

### The write format — SOLVED, VERIFIED end to end

Output report `0xe0`, 265 bytes. The header is **four u16 little-endian
fields** describing a sub-rectangle, then the bitmap:

| Byte | Field | Units |
|---|---|---|
| `[0]` | report ID `0xe0` | — |
| `[1:3]` | **x offset** | pixels |
| `[3:5]` | **y offset** | **pages** (1 page = 8 rows) |
| `[5:7]` | **width** | pixels |
| `[7:9]` | **height** | **pages** |
| `[9:265]` | bitmap | `width × height` bytes |

The mixed units are the trap: **x and width are pixels, y and height are
pages.** A 128 × 32 panel is 4 pages, so any header asking for h ≥ 8 is
off-panel and gets dropped.

Tilings, all rendering the same test image, **all verified on this unit**:

```
(x=0,y=0,w=64,h=4)  + (x=64,y=0,w=64,h=4)              left/right  VERIFIED
(x=0,y=0,w=64,h=2)  + (64,0,64,2) + (0,2,64,2)
                    + (64,2,64,2)                      quadrants   VERIFIED
(x=0,y=0,w=128,h=2) + (x=0, y=2,w=128,h=2)             top/bottom  VERIFIED
(0,p,128,1) for p in 0..3                              rows        VERIFIED
```

`w=128` was the last width confirmed, and it matters more than it looks: the
driver recommendation below rests entirely on full-width bands, and until it was
rendered every verified tiling had used `w=64`. Each was checked by blanking the
panel with an already-verified tiling and then drawing *only* with the tiling
under test, so a silently-discarded write shows up as a dark panel rather than
hiding behind the previous image.

### Partial updates work — VERIFIED

The quadrant tiling is the important one. Each of its four reports carries
`64 × 2 = 128` meaningful bytes inside the fixed 256-byte payload, and the
image renders correctly. So:

- **`width × height` need not equal 256.** The device honours the header as a
  true sub-rectangle and ignores the unused tail of the payload. (Every known
  upstream example happens to fill the payload exactly, so this was not
  predictable from cabl.)
- **Arbitrary regions can be repainted independently** — one track name, one
  parameter value, without touching the rest of the panel.

### Short reports do NOT work — VERIFIED, and this caps the whole optimisation

The obvious way to make a small region cheap is to write only
`ID + 8 header + width × height` bytes. **Tested and it corrupts the panel.**

Controlled test, both after blanking with full-length writes, same four
`(0, page, 128, 1)` regions, same image, differing only in report length:

| Report length | Result |
|---|---|
| 137 B (`9 + 128`) | **corrupted** — pages 1 and 3 missing, diagonal broken, border verticals alternating on/off per page |
| 265 B (full) | **clean** |

The kernel accepts the short write without error; the device does not render it
correctly. So **every `0xe0` report costs a fixed 265 bytes**, no matter how
small the rectangle in its header.

The corruption pattern — whole pages missing, alternating — is consistent with
the device always consuming 256 payload bytes regardless of what the host sent,
reading whatever follows a short transfer. That is a plausible mechanism rather
than a confirmed one, but it needs no action: the conclusion is the same either
way, and page-granular failure is exactly what it predicts.

An earlier version of this section claimed a small region was "the difference
between one transfer and several." That was wrong twice over — the host writes
the whole report regardless, and short reports do not even work.

### What this means for a driver — use a page span, not fixed halves

Because a report is fixed-size but carries up to 256 payload bytes, and a
full-width band is 128 bytes per page, a **2-page band costs exactly what a
1-page band costs**. Widening is free. That single fact drives everything:

- A **full frame is 2 reports** (`lr` or `tb`). ~530 bytes.
- **Any** update costs **at least 1 report**, so the whole achievable win is
  2 reports → 1.
- **For full-width content, horizontal narrowing is worthless.** No width takes
  a report below 1, and short reports don't work. Given full-width dirty
  regions, the vertical page span is the only axis with leverage. See the
  precondition below — this is *not* true in general.

A fixed top/bottom dirty flag is the obvious scheme and it is **not optimal**.
Text rows 1 and 2 straddle the `tb` boundary, so fixed halves costs 2 reports
where a single band `(0, y=1, 128, 2)` covers both in 1. There are three
possible 2-page bands (starting at page 0, 1 or 2); `tb` only ever uses two of
them. And rows 1+2 is the *common* case for this layout — a parameter name with
its value on the next row.

The fix is a min/max over four dirty bits, not an allocator:

```
span = [min(dirty_pages), max(dirty_pages)];   n = max - min + 1
n <= 2  ->  1 report:  (0, min, 128, 2)      # widen to 2, it is free
n == 3  ->  2 reports
n == 4  ->  2 reports                        # same as tb
```

Implemented as `FB.encode_dirty()` in `tools/a61fb.py`. Exhaustively checked
against all 16 dirty-page subsets: **never worse than `tb`, strictly better for
`{1,2}`**, and every dirty page covered in every case.

Note `min` must be clamped to `PAGES - 2` so a lone dirty page 3 widens upward
to the band `(2,3)` rather than off-panel.

### Precondition — this is optimal only while every dirty region is full-width

**Do not read the above as "nothing can beat a page span."** The true optimum is
the dirty region's **2D bounding box** subject to `w × h <= 256`. The page-span
algorithm is the special case that always takes `w = 128`, which is optimal for
full-width text rows and nothing else.

It loses whenever a dirty region is **horizontally narrow and vertically tall**.
The concrete case, and a natural thing to want on a control surface:

> A vertical level meter, 16 px wide on the right edge, spanning all four pages,
> animating continuously while the text rows stay static.
>
> - Page span sees dirty `{0,1,2,3}`, span 4 → **2 reports per refresh**.
> - Bounding box `(x=112, y=0, w=16, h=4)` = 64 bytes → **1 report**.

That is a 2× saving on what would be the most frequently updating element on the
panel — the one place the traffic actually matters.

**So the precondition is: every dirty region is full-width.** Text rows always
are, so the current design is safe. But if anyone later adds a narrow
always-animating element — a meter, a clock, a small indicator — the assumption
silently becomes wrong and the only symptom is a quietly doubled report rate.
Nothing breaks, nothing logs, it just costs twice what it should.

If that day comes, generalise `encode_dirty()` to track a bounding box in both
axes and emit `(x0, page0, w, h)` when `w × h <= 256`, falling back to the page
span otherwise. Until then, the simpler version is the right call.

Constraint: `width × height <= 256`. And x, width are pixels while y, height
are pages, so vertical extent is quantised to 8-row boundaries — a 1-pixel-tall
change still costs a full page.

### Two design conclusions that follow from the numbers

**1. Design the font at 8 px. The panel is four 8 px text rows, updated in pairs.**

An 8 px font means glyphs never straddle a page boundary, so a text row is
exactly one page and the encoder needs no cross-page composition at all. A 7 px
font at arbitrary y would manufacture exactly the complexity this geometry hands
you for free.

The panel is then four text rows:

```
page 0   rows  0-7    text row 0   \  one 128x2 report
page 1   rows  8-15   text row 1   /
page 2   rows 16-23   text row 2   \  one 128x2 report
page 3   rows 24-31   text row 3   /
```

Rows are updated **in pairs**, because `128 × 2 = 256` is the payload ceiling and
a pair costs the same single report as a lone row would. But the pair is *not*
fixed to `{0,1}` and `{2,3}` — it is whichever 2-page band covers the dirty
span, which is what makes rows 1+2 cost one report instead of two. See
`FB.encode_dirty()`.

(`tools/a61fb.py` also has `tiling="rows"` at 4 × `128 × 1`, but it is a test
convenience only — it costs twice as many reports for the same frame.)

**2. There is no room for an S-series-style eight-column parameter strip.**

128 pixels across 8 knobs is **16 pixels per knob** — about three characters at
any legible width. The S-series layout does not transfer.

The panel should instead show the **touched** knob's parameter name and value,
which is what input bits 25–32 are for. That is a better interaction regardless
of pixel budget: it gives the full width to the thing the user's finger is
actually on, and it needs no mode switching. Falls back to track name / transport
state when nothing is touched.

Pixel data is **page-major** within a report:

```
data[local_page * width + col]
```

Each byte is **8 vertical pixels** of one column within its page, and
**bit 0 is the TOP row** — SSD1306-style page packing.

To be precise about two things that are easy to conflate: the **header** is a
bounding box (in mixed units), and the **payload** is SSD1306 page-major. Both
are true, of different parts of the report. The early failures came from
assuming the header was a bounding box *in pixels for all four fields*, not
from the bounding-box idea itself.

**Polarity is inverted: a SET bit renders DARK, a CLEAR bit renders LIT.**
So an encoder that thinks in "1 = lit" must XOR `0xff` on the way out.

This is the one part of the format that is **not** predicted by any upstream
source — cabl, DrivenByMoss and the Maschine write-ups describe the header and
the page packing but none mention inversion. It is also the single most
misleading detail, because it makes the natural first test ("blank the panel by
writing zeros") light the panel *fully*, which reads as a failure. Anyone
reproducing this on other A-series hardware should check polarity before
concluding their writes are being dropped.

Reference encoder: `tools/a61fb.py` (`FB.encode()`). That method is the piece
that transplants into C++; the drawing primitives around it are convenience.

Verified by `tools/a61fb.py selftest`, which renders a 1px border on all four
edges, a corner-to-corner diagonal, an 8×8 block at x=100 and a 4×4 block at
x=4. All four appear correctly positioned and the diagonal is **smooth** — a
wrong bit order would break it into a four-segment staircase, one per page.

### Why this was missed, here and upstream

Worth recording, because the failure mode was actively misleading:

1. Every earlier attempt used Ardour's Maschine **Mikro** geometry — 128 × 64
   in four stripes. The A61 panel is 128 × 32. The firmware **validates the
   header and silently discards out-of-range writes**, so every wrong guess
   returned success with no visible effect.
2. Inverted polarity meant the natural "blank it first" write of all-`0x00`
   lights the panel *fully*, and a test sequence ending on `0x00` leaves it
   fully lit — which reads as "stale content" or "wedged", not "working".

Those two together mean a *correct* write looked identical to a failed one
unless you knew the polarity. The "total silence rather than garbage" reasoning
that pointed at a handshake was sound logic from unsound premises: the firmware
was validating, not ignoring.

### Prior art — this appears to be the first open-source solution

No open-source project drives this panel on Linux, for this device generation:

- **komplementary-kontrol** is the only A-series Linux project, and contains no
  display-write code at all.
- **qKontrol** solves the MK2 displays and its README explicitly excludes ours:
  "the models M32, A25, A49 and A61 are also different hardware and not
  compatible."
- **KompleteSynthesia** lists PIDs for S-series MK1/MK2/MK3 only — no A, no M32.
- **DrivenByMoss** supports A/M through NI's Host Integration service, which is
  Windows/macOS only.

Everything that *does* put text on an A-series panel does so on Windows or
macOS through NIHIA, which renders host-side and pushes pixels. The A61 has no
bulk endpoint (see USB topology), so HID `0xe0` was always the only candidate.

**Correction to an earlier version of this document:** it cited
[FLIN](https://github.com/marcora/FLIN)'s *"OLED doesn't change status at all"*
TODO as evidence that the HID path was unsolved. That was a misreading — FLIN
is a **Windows FL Studio Python script** that drives the M32 through NIHIA, so
its TODO is a bug in its NIHIA usage and says nothing about HID. reaKontrol,
using the same NIHIA path, *does* get track names onto A/M screens.

The `0xe0` header semantics are corroborated by cabl, which uses the identical
four-u16 layout on the Maschine Mikro MK2 and Maschine MK2, and by
DrivenByMoss's Kontrol MK1 USB path. Independent of our hardware work, those
sources predict exactly the `(0,0,64,4)+(64,0,64,4)` header that was found here
empirically.

**Do not model the Ardour Maschine Mikro path.** `m2_dev_mikro.cc` declares
`w=0x20, h=0x08` while packing 16 bytes per row over 16 rows — internally
inconsistent, and it disagrees with cabl's header for the same device. Ardour's
*MK2* path does match cabl. The early attempts here failed partly because they
faithfully reproduced Ardour's Mikro bug.

A USB capture against NI's own software on Windows/macOS was the planned
fallback. It was not needed.

### What was eliminated along the way — now explained

Kept as history, and because it shows what the failure mode looked like. Every
attempt below was accepted by the kernel with no error and produced no visible
change. All of them are now explained by the wrong geometry (128 × 64 four-stripe
against a 128 × 32 panel) being rejected by the firmware's header validation.

| Attempt | Result |
|---|---|
| `0xe0` header `(0, 0, 128, 16)` — bounding box guess | nothing |
| `0xe0` header `(32*l, 0, 0x20, 0x08)` — as Ardour's Mikro | nothing |
| `0xe0` header `(0, 16*l, 0x20, 0x08)` — as Ardour's MK2, row units | nothing |
| `0xe0` header `(16*l, 0, 0x20, 0x08)` | nothing |
| `0xe0` header `(0, 32*l, 0x20, 0x08)` | nothing |
| `0xf8` SET_FEATURE, enable/brightness fields | **EPIPE — device STALLs** |
| `0xf4` as a text path, command bytes 0x00/0x01/0x02 | nothing |
| `0xf4`, `payload[0]` swept `0x00`–`0x1f`, ASCII in `payload[1..]` | nothing |
| `0xe0` 4-stripe Mikro convention, hammered at 1 Hz **in MIDI mode** | nothing |

The reasoning that these negatives supported — "total silence means a missing
unlock handshake" — was **wrong**, and it is worth being explicit about why,
because it cost the most time:

- It leaned on the `0xf8` `SET_FEATURE` STALL as corroboration. `0xf8` is a
  read-only capability block, so that STALL needs no handshake to explain it.
- It assumed a wrong header would *shear* the image rather than be rejected. A
  firmware that validates the header and drops out-of-range writes produces
  exactly the silence observed. That is what this one does.
- Inverted polarity hid the successes. A test ending on all-`0x00` leaves the
  panel **fully lit**, which was repeatedly read as "stale" or "wedged".

No handshake, no unlock, no focus request. Just the wrong geometry and the
wrong sign.

**A malformed `0xe0` report is not dangerous.** Many hundreds of wrong-geometry
writes were sent across this session at up to ~80 reports/sec, in both modes,
and the device never crashed, reset, or dropped off the bus. The only device
loss in the whole session was a deliberate hand replug.

### Mode: verified in interactive only

Every successful render was in **interactive mode** (`a0 03 04`). Whether
correct-geometry writes also render in MIDI mode is **UNTESTED** — the one
MIDI-mode attempt used the wrong 128 × 64 geometry, so it establishes nothing.
Not worth chasing: a control surface wants interactive mode regardless, for the
endless knobs and for Shift.

Note the one-way handoff: once interactive mode has been entered, the firmware
stops drawing the panel and does **not** resume when switched back to MIDI mode.
It stays on whatever was last written until replug. For a control surface this
is the desired behaviour — the host keeps the panel — but it does mean a user
who quits Ardour is left with the last frame we drew. **Blank the panel on
teardown** (`tools/a61fb.py clear`).

### The firmware releases the panel in interactive mode — VERIFIED

In MIDI mode the firmware actively drives the screen: it renders CC readouts
as knobs move, and paging through the four preset pages updates the display.

After `a0 03 04`, **the screen freezes on its last MIDI-mode contents** and
stops responding to knob movement and page changes entirely. A panel holding a
stale image is what you see when nothing is driving it any more.

This is independent confirmation that the mode switch engaged — separate from
the knob evidence — and it means the display is host-owned in interactive
mode, so writes should not contend with firmware rendering.

### Upstream's display corruption — most likely geometry, not a race

Upstream reports the OLED garbled on two separate units, and the second knob
label on every preset page corrupted "regardless of correct data being sent."

This document previously argued that was a race against firmware rendering.
That explanation is now much less likely. A host writing 128 × 64 four-stripe
data to a 128 × 32 panel gets: stripe 0 partially valid, stripes 1–3 rejected
or wrapped, and — with inverted polarity — a background that is lit where it
should be dark. "Garbled, always in the same place" is exactly what a fixed
geometry mismatch produces, and it explains the *reproducibility across two
units* far better than a race does. Races are not that repeatable.

**Recommendation for anyone revisiting upstream's code: check the geometry and
the polarity before assuming concurrency.**

---

## Sysex — a working bidirectional channel — VERIFIED

The A61 answers sysex, which makes this the only **request/response** channel
we have. Every HID output report is fire-and-forget: a write either does
something visible or is silently discarded, with no way to tell which. Sysex
gives feedback, so protocol work here can be automated instead of requiring a
human to watch the panel.

### Reaching it on Linux

**The rawmidi path is held by PipeWire**, so `amidi -p hw:2,0` fails with
`EBUSY` **even as root**. Confirmed, not inferred — `/proc/asound/card2/midi0`
names the owner:

```
Output 0
  Owner PID    : 3660        <- pipewire
```

Note no process shows an fd on `/dev/snd/midiC2D0` in `/proc/*/fd`, so looking
there suggests the node is free. It is not; the procfs owner field is the
reliable check. On a system where PipeWire is not managing the device, `amidi`
may well work — but the sequencer path works either way, so prefer it:

```
aseqdump  -p 24:0            # what the device sends
aplaymidi -p 24:0 file.mid   # send to the device
```

`aplaymidi` takes a file, so sysex has to be wrapped in a format-0 SMF;
`tools/mksysex.py` generates one.

**Access requires the `audio` group.** `/dev/snd/seq` is `root:audio 0660` and
is a *global* node, so a per-device udev ACL cannot reach it — group membership
is the only lever. Beware a misleading detail: `midiC2D0` and `controlC2` may be
world-writable from an incidental udev rule, which makes it look as though no
group is needed. The rawmidi path they expose is the one PipeWire has taken.

Group membership only applies to sessions started afterwards. A long-running
process keeps its old supplementary groups; `sg audio -c '<cmd>'` gets a fresh
group context without re-login and without a password.

### Universal Identity Request — VERIFIED

Send `F0 7E 7F 06 01 F7`, receive:

```
F0 7E 7F 06 02  00 21 09  30 17  3D 00  00 00 01 00  F7
```

| Field | Value | Meaning |
|---|---|---|
| `00 21 09` | | Native Instruments manufacturer ID |
| `30 17` | `0x1730` | device family — **identical to the value in HID feature reports `0xd0`/`0xd8`** |
| `3D 00` | `0x3D` = 61 | family member — the model number, i.e. **A61** |
| `00 00 01 00` | | firmware revision |

Two things worth keeping: the family word `0x1730` is shared across the HID and
sysex protocols (and is *not* the USB PID `0x1750`), and the member code is
just the key count, so A25/A49 presumably report `0x19`/`0x31`.

### Not a display path — do not pursue the `konfigure` preset mechanism

An earlier version of this document proposed deriving the sysex `konfigure`
preset payload in order to push text to the panel. **That is obsolete and
should not be attempted.** Two reasons:

1. It was premised on upstream's display corruption being firmware contention
   that interactive mode would remove. This document later retracts that — see
   "Upstream's display corruption — most likely geometry, not a race."
2. Even if it worked it would be a **downgrade**. It is a firmware-rendered
   fixed-label mechanism; the `0xe0` framebuffer is host-rendered, arbitrary,
   and already works in the mode the driver runs in.

The sysex channel keeps its value for the identity response and as a
request/response probe. It is not the way to draw on the screen.

## Device info feature reports (read-only, non-invasive)

| Report | Content |
|---|---|
| `0xd0` | `01 00 | 30 17 | 03 ff…` — u16 `0x0001`, u16 `0x1730` |
| `0xd8` | u16 `0x0100`, u16 `0x1730`, u16 unit ID (matches `HID_UNIQ`), u32 firmware build time (Unix seconds) |
| `0xd9` | 25-char ASCII serial, `A61`-prefixed, zero-padded to 32 B |
| `0xf8` | display config, above |

Per-unit values (serial, unit ID) are redacted; the layouts above are what
transfers. `0xd9` being an `A61`-prefixed ASCII serial suggests the prefix is
the model, so A25/A49 likely differ there.

`0x1730` appears in both `0xd0` and `0xd8`, and the byte pair `30 17` also
appears in upstream's published sysex lead-in
(`f0 00 21 09 30 17 …`) — so it is a device/product identifier shared between
the HID and sysex protocols. Note it is **not** the USB PID (`0x1750`).

---

## Open questions

Only these remain. **Everything else in this document is VERIFIED — the
button bitfield table in particular is complete and should not be re-derived.**

1. Whether LED brightness is genuinely continuous over the declared 0..127
   range, or quantised to a few steps. Cosmetic; affects Phase 4 polish only.
2. Output report `0xf4` (1 + 31 bytes, purpose unknown). Does not block
   anything. It is *not* a text path — `payload[0]` was swept `0x00`–`0x1f`
   with ASCII behind it and the panel never changed.
3. Whether correct-geometry `0xe0` writes also render in MIDI mode. Untested,
   and not worth testing — a surface wants interactive mode anyway.
4. A font. The framebuffer and its primitives exist; nothing renders glyphs yet.
   That is Phase 4 work, not protocol work.

### `payload[28]` is the octave base note — RESOLVED

Was open question 2. Settled 2026-08-10 by pressing Octave Up once and Octave
Down once while tracing the whole payload from the Ardour surface:

```
KKA button Octave Up (bit 20) pressed      KKA payload[28] 36 -> 48
KKA button Octave Down (bit 19) pressed    KKA payload[28] 48 -> 36
```

Exactly +12 and back — one octave. The A61's keys are notes 36–96, so `36` is
the resting value because it *is* the bottom key. This confirms the hypothesis
that came from `isovector/free-m32`, which names the equivalent M32 field
`keyshift`, and the field should be read as **the MIDI note number of the
lowest key**. Update the `[28]` row above accordingly; it is no longer unknown.

Two further results from the same session, both confirming what was already
recorded rather than changing it:

- **The analog block really is inert over HID.** Full pitch-wheel and mod-wheel
  sweeps moved nothing in `[21:27]`, tracing every byte. The **VERIFIED silent**
  status in the payload table holds in interactive mode too, not just MIDI mode.
- **Keys never reach HID at all.** Playing keys produced no input report
  whatsoever. The keybed leaves over the device's own MIDI port, which is what
  lets one surface module serve A25/A49/A61 with no per-model decode.

### Bits 22 / 23 — ours is right, upstream is wrong

`hugovangalen/komplementary-kontrol` names bit 22 "4D Right" and bit 23
"4D Left". This document has had them the other way round, from capture. That
disagreement is now settled empirically: pressing the 4-D directions in the
order Up, Left, Right, Down produced bits 21, 22, 23, 24 in that order.

**Bit 22 is Left and bit 23 is Right.** Upstream's dispatch loop is bounded by
`TOTAL_HID_BUTTONS == 21`, so it never dispatched either bit and its names for
them were never exercised.

**Resolved and not to be revisited:** the complete 34-control button map
including bits 19/20 (Octave Down/Up), 33 (4-D Press) and 34–39 (padding);
touch-sensor bit ordering and direction; 4-D encoder encoding; knobs endless
in HID under interactive mode; both mode words and their effects; Shift being
firmware-swallowed in MIDI mode; mode not surviving a power cycle; **LED index
being identical to button bit index for 0–20**; **the entire display write
path — geometry, addressing, bit order and polarity**.
