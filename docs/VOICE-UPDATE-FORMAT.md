# What to say in a voice update

Derived from what the pipeline actually extracts, not from a style guide. Stages:

    audio → Parakeet ASR → LLM extracts the 3 C's → resolver → validator → event log

The LLM only reads language. It never decides state, computes hours or picks an
operation code — all of that is deterministic downstream, which is why the
wording below matters more than the fluency.

---

## The shape

**Concern, Cause, Correction** — the documentation standard already on every
repair order. Say them in that order and the extraction has nothing to guess.

> Update for repair order **RO-26-08031**.
> *Concern:* Customer states a grinding noise from the front under braking.
> *Cause:* Front pad thickness one point eight millimetres against a three
> millimetre minimum, discs scored.
> *Correction:* Completed the front brake pads and rotors R and R, one point nine
> hours. Rear brake inspection still to do. Recommending a brake fluid flush,
> needs customer authorisation.

---

## The eight things that are captured

| Say this | Captured as | If you leave it out |
|---|---|---|
| the repair order number | `ro_number` | it asks which RO, and lists candidates |
| what the customer reported | `concern` | the RO keeps its original concern |
| what you found | `cause` | nothing recorded against the finding |
| work finished, with hours | `OP_COMPLETED` | the work is invisible to proficiency and handover |
| work still outstanding | `OP_PENDING` | the RO looks finished when it is not |
| work you advise | `OP_RECOMMENDED` | no authorisation prompt is raised |
| a measurement **and its minimum** | `MEASUREMENT_TAKEN` | **no safety flag** — see below |
| a part number and availability | `PARTS_ORDERED` | no parts hold, no blocker |

### Repair order

Say it. `"repair order RO-26-08031"` resolves at confidence 1.0. Spoken digits
work — *"oh eight oh three one"* — and so does a bare suffix, *"repair order eight
zero three one"*, **provided it is unique**; if it matches more than one, the
pipeline asks rather than picking. The acceptance threshold is 0.90, deliberately
strict: applying an update to the wrong vehicle is the one error nothing
downstream can correct.

On the Technician Update tab the RO dropdown overrides whatever you said. To test
resolution from speech alone, clear it first.

### Hours

Say them as a decimal: *"one point nine hours"*. Anything outside 0 to 24 is
dropped as implausible, and the operation is still recorded — just with no time
against it. Say the hours for **each** operation, not a total for the update;
totals are computed, never dictated.

### Naming the work

Use the words on the operation, not a paraphrase. The resolver blends three fuzzy
scorers against the catalogue and accepts at 0.62, and since pass 15 a candidate
must share at least one *distinctive* word with what you said. Generic
vocabulary — replacement, repair, inspection, service, front, rear, R&R — no
longer carries a match on its own.

- *"front brake pads and rotors"* → `BRK-FR-PAD` ✓
- *"two front tyres"* → `TYR-MOUNT-BAL` ✓
- *"vehicle health check"* → **asks.** There is no VHC operation in the
  catalogue, only four specific inspections. Name the one you did — *"front brake
  inspection"*, *"tyre tread check"*, *"suspension and steering inspection"*.

Trade shorthand is expanded before matching: C/S, R&R, NSF/OSF/NSR/OSR, NLA, TSB,
DPF, EGR, VHC, discs→rotors, cambelt→timing belt, regas→evacuate and recharge.
Front and rear are matched explicitly, so saying *"rear"* will not land a front
operation.

### Measurements — the one rule that matters most

**Always say the specification alongside the value.**

> *"Front pad thickness one point eight millimetres, minimum is three."*

Without the minimum there is nothing to compare against: `out_of_spec` stays
false, `safety_related` stays false, the severity never becomes
`SAFETY_RELATED`, and the vehicle does not appear in *"which vehicles cannot be
released on safety grounds?"*. The value alone is just a number.

Conventional names and their minima: `front_pad_thickness` / `rear_pad_thickness`
3.0mm, `tyre_tread_nsf` / `osf` / `nsr` / `osr` 1.6mm, `battery_cca`.

### Fault codes

Only genuine SAE codes survive — the catalogue holds 26, including P0171, P0300,
P0420, P0430, P0455, U0100. Read them out character by character: *"P zero one
seven one"*. **Anything not in the list is dropped silently**, so if a code
matters and does not appear in the diff card, that is why.

### Parts

Part number, then availability in one of four ways: *in stock*, *next day*,
*on back order*, *no longer available*. Anything else defaults to next day. A
back-ordered or NLA part is what puts the job on hold and makes it a blocker in
the handover.

### State

Only four phrases move the repair order: *parts hold*, *awaiting authorisation*,
*repair in progress*, *quality control*. Say nothing and the state is left alone,
which is usually right. An illegal transition **rejects the whole update** with an
explanation rather than applying half of it.

---

## What not to say

- **Don't total anything.** No "three and a half hours all in". Per operation only.
- **Don't authorise.** *"Customer approved, go ahead and order it"* is refused by
  the action rail — only a person authorises work.
- **Don't guess a code or a part number.** An invented code is dropped; an
  invented part number is recorded as fact.
- **Don't say "the usual"** or *"sorted the thing at the front"*. It will ask, and
  a question you have to answer twice is slower than saying it once.
- **Don't report work complete on a job still awaiting authorisation.** That is a
  blocking conflict and the update will not apply — correctly.

---

## The transcript to test with

Read this aloud at normal dictation pace. Substitute a repair order number from
your own database — `.venv/bin/python scripts/test_voice_update.py` prints one.

> Update for repair order R O twenty six, zero eight zero three one. Customer
> states a grinding noise from the front of the car under braking, worse when
> cold. Road tested and confirmed the noise. Front brake inspection shows front
> pad thickness at one point eight millimetres against a three millimetre
> minimum, and the discs are scored. I have completed the front brake pads and
> rotors R and R, that took one point nine hours. Rear brake inspection still to
> do. Recommending a brake fluid flush and bleed as the fluid is dark, that needs
> customer authorisation.

That exercises: RO resolution, concern, cause, one completed operation with
hours, one pending, one recommended, an out-of-spec measurement that raises the
safety flag, and a state change to repair in progress.

Five or six events, depending on the repair order: if it is already in `REPAIR_IN_PROGRESS` the
state signal matches the current state and no `STATE_CHANGED` is recorded. A
redundant state change is deliberately not written.

Expected diff card:

```
  ✓ Front brake pads & rotors R&R           1.9 hr   (flat rate 1.8)
  + Brake fluid flush & bleed              RECOMMENDED - needs authorisation
  ⚠ front_pad_thickness 1.8mm below minimum 3.0mm → SAFETY_RELATED
  ⛔ State → REPAIR_IN_PROGRESS
  ○ Rear brake inspection & measure still pending
```

---

## Running it

```bash
.venv/bin/python scripts/test_voice_update.py            # list the samples
.venv/bin/python scripts/test_voice_update.py 1          # dry run: every stage
.venv/bin/python scripts/test_voice_update.py 1 --apply  # commit it
.venv/bin/python scripts/test_voice_update.py 1 --no-llm # deterministic half only
.venv/bin/python scripts/test_voice_update.py --audio note.wav
.venv/bin/python scripts/test_voice_update.py --text "your own dictation"
```

A dry run copies the database to a temporary file and reconciles against the
copy, so you get the real diff card, the real conflict detection and the real
state transition with nothing written. Only `--apply` touches your data.

`--no-llm` feeds the validator a hand-written payload instead of calling the
model, which tests operation resolution, measurement validation, conflict
detection and the event write with the NIMs down.

In the UI: **Technician Update → Record or upload → Transcribe**. The transcript
lands in an editable box — always read it before submitting, because ASR will
mishear a part number. Then **Extract and apply**, and the same diff card appears
beside the extracted JSON.

Submitting the same update twice is worth trying: the second one raises a
`REPEAT_OP` conflict asking whether it is rework or a comeback, instead of
booking the hours again.
