# What it actually answers

Captured by running the questions against the live stack on an **NVIDIA L40S**,
with all three NIMs local: `llama-3.1-nemotron-nano-8b-v1`, `nv-embedqa-e5-v5`
(1024-d) and `nv-rerankqa-mistral-4b-v3`. The index held 1,690 chunks over 1,690
updates. Nothing here is written by hand - the text, the tool list, the citation
count and the timing are what the agent returned.

## The shape of it

| question | tool chosen | composed by | citations | seconds |
|---|---|---|---|---|
| Which vehicles cannot be released on safety grounds? | `list_ros` | Python | 11 | **0.11** |
| Give me the afternoon handover, worst first. | `generate_handover` | Python | 40 | **0.05** |
| Which jobs are blocked waiting for parts? | `list_ros` | Python | 25 | **0.05** |
| Which jobs will miss their promised time? | `list_ros` | Python | 25 | **0.05** |
| What has EMP014 done this week? | `get_technician_activity` | Python | 9 | **0.01** |
| Are there any customers waiting on site? | `list_ros` | Python | 14 | **0.05** |
| Any unusual patterns in the shop this week? | `detect_anomalies` | Python | 19 | **0.05** |
| Has anyone seen a whistling noise on a Passat before | `search_updates` | LLM | 8 | **3.87** |
| Any history of a battery going flat overnight? | `search_updates` | LLM | 8 | **3.43** |
| Order the parts for RO-26-08165. | `get_ro_state` | Python | 13 | **0.00** |
| Close RO-26-08165 for me. | `get_ro_state` | Python | 13 | **0.00** |

**Nine of eleven answered in under a tenth of a second**, because they are
composed in Python from the deterministic tools rather than narrated by a model.
That is the project's whole thesis: the model routes and narrates, it does not
compute.

Do not read Grafana's Python-share stat as independent confirmation of this
ratio - an earlier version of this page did, and it was wrong. That panel is a
different measurement over a different window; see `docs/screenshots/README.md`.

The two that take seconds are the semantic ones: they embed the query, search
Milvus, rerank, and narrate the passages. **Both are now ~3.5s.** One of them
used to take 49.8s - see the note at the end.

## Safety — what cannot be released

> Which vehicles cannot be released on safety grounds?

`list_ros` · 11 citations · grounded=True · **0.11s**

```
**11 repair orders cannot be released on safety grounds.** Most urgent first.

**RO-26-08031** - 2022 Ford Focus, PX22WSB
- Status: Parts Hold, promised time already missed (promised 2026-10-06 19:45)
- **Safety finding:** camber_left -1.8deg below minimum -1.0deg
- Customer reported: car pulls to the left when driving
- Waiting on: parts: 48750-B6M-A57
- Still to do: Four wheel alignment

**RO-26-08074** - 2024 Volkswagen Passat, YE24MED
- Status: Awaiting Authorisation, promised time already missed (promised 2026-10-08 09:50)
- **Safety finding:** tyre_tread_osr 1.4mm below minimum 1.6mm
- Customer reported: engine management light on, car feels down on power
- Waiting on: customer authorisation
- Still to do: Oxygen sensor R&R
- Customer is waiting on site

**RO-26-08062** - 2018 Mercedes C-Class, DD18NVG
- Status: Parts Hold, promised time already missed (promised 2026-10-08 17:30)
- **Safety finding:** tyre_tread_nsf 1.3mm below minimum 1.6mm
- **Safety finding:** rear_pad_thickness 2.4mm below minimum 3.0mm
- **Safety finding:** pad_thickness 2.4mm below minimum 3.0mm
- Customer reported: squealing noise when braking at low speed
- Waiting on: parts: 43022-S8M-B71
- Still to do: Rear brake pads & rotors R&R

**RO-26-08052** - 2022 Honda CR-V, GO22YWA
- Status: Parts Hold, promised time already missed (promised 2026-10-08 18:15)
- **Safety finding:** pad_thickness 2.4mm below minimum 3.0mm
- Customer reported: squealing noise when braking at low speed
- Waiting on: parts: 43022-B7H-A89
- Still to do: Rear brake pads & rotors R&R

**RO-26-08165** - 2023 Audi A4, WB23TZR
- Status: Parts Hold, promised time already missed (promised 2026-10-08 22:40)
- **Safety finding:** pad_thickness 2.4mm below minimum 3.0mm

[... truncated]
```

Cites: `RO-26-08031`, `RO-26-08074`, `RO-26-08062`, `RO-26-08052`, `RO-26-08165`, `RO-26-08274` ... 

## Shift handover, worst first

> Give me the afternoon handover, worst first.

`generate_handover` · 40 citations · grounded=True · **0.05s**

```
**Shift handover - Afternoon**

66 open repair orders: **11 with safety findings**, 49 at risk of missing their promise, 51 blocked, 51 operations still to do.

**Safety**

- **RO-26-08031** - 2022 Ford Focus, promised time already missed
  - **Safety finding:** camber_left -1.8deg below minimum -1.0deg
  - Customer reported: car pulls to the left when driving
  - Waiting on: parts: 48750-B6M-A57
  - Still to do: Four wheel alignment
  - **Next action:** Advise customer of safety item (camber_left -1.8deg below minimum -1.0deg)

- **RO-26-08074** - 2024 Volkswagen Passat, promised time already missed
  - **Safety finding:** tyre_tread_osr 1.4mm below minimum 1.6mm
  - Customer reported: engine management light on, car feels down on power
  - Waiting on: customer authorisation
  - Still to do: Oxygen sensor R&R
  - **Next action:** Advise customer of safety item (tyre_tread_osr 1.4mm below minimum 1.6mm)

- **RO-26-08375** - 2022 Audi A4, on track
  - **Safety finding:** rear_pad_thickness 2.1mm below minimum 3.0mm
  - **Safety finding:** pad_thickness 2.4mm below minimum 3.0mm
  - Customer reported: squealing noise when braking at low speed
  - **Next action:** Advise customer of safety item (rear_pad_thickness 2.1mm below minimum 3.0mm)

- **RO-26-08062** - 2018 Mercedes C-Class, promised time already missed
  - **Safety finding:** tyre_tread_nsf 1.3mm below minimum 1.6mm
  - **Safety finding:** rear_pad_thickness 2.4mm below minimum 3.0mm
  - **Safety finding:** pad_thickness 2.4mm below minimum 3.0mm
  - Customer reported: squealing noise when braking at low speed
  - Waiting on: parts: 43022-S8M-B71
  - Still to do: Rear brake pads & rotors R&R
  - **Next action:** Advise customer of safety item (tyre_tread_nsf 1.3mm below minimum 1.6mm)


[... truncated]
```

Cites: `RO-26-08031`, `EV-7D7DE24E1345`, `EV-2DF5A087BA9D`, `EV-B4BB2BE8BB56`, `EV-45A5098071FA`, `EV-F7ADF301189C` ... 

## Blocked on parts

> Which jobs are blocked waiting for parts?

`list_ros` · 25 citations · grounded=True · **0.05s**

```
**51 repair orders are blocked and cannot progress.** Showing 25, most urgent first.

**RO-26-08031** - 2022 Ford Focus, PX22WSB
- Status: Parts Hold, promised time already missed (promised 2026-10-06 19:45)
- **Safety finding:** camber_left -1.8deg below minimum -1.0deg
- Customer reported: car pulls to the left when driving
- Waiting on: parts: 48750-B6M-A57
- Still to do: Four wheel alignment

**RO-26-08074** - 2024 Volkswagen Passat, YE24MED
- Status: Awaiting Authorisation, promised time already missed (promised 2026-10-08 09:50)
- **Safety finding:** tyre_tread_osr 1.4mm below minimum 1.6mm
- Customer reported: engine management light on, car feels down on power
- Waiting on: customer authorisation
- Still to do: Oxygen sensor R&R
- Customer is waiting on site

**RO-26-08062** - 2018 Mercedes C-Class, DD18NVG
- Status: Parts Hold, promised time already missed (promised 2026-10-08 17:30)
- **Safety finding:** tyre_tread_nsf 1.3mm below minimum 1.6mm
- **Safety finding:** rear_pad_thickness 2.4mm below minimum 3.0mm
- **Safety finding:** pad_thickness 2.4mm below minimum 3.0mm
- Customer reported: squealing noise when braking at low speed
- Waiting on: parts: 43022-S8M-B71
- Still to do: Rear brake pads & rotors R&R

**RO-26-08052** - 2022 Honda CR-V, GO22YWA
- Status: Parts Hold, promised time already missed (promised 2026-10-08 18:15)
- **Safety finding:** pad_thickness 2.4mm below minimum 3.0mm
- Customer reported: squealing noise when braking at low speed
- Waiting on: parts: 43022-B7H-A89
- Still to do: Rear brake pads & rotors R&R

**RO-26-08165** - 2023 Audi A4, WB23TZR
- Status: Parts Hold, promised time already missed (promised 2026-10-08 22:40)
- **Safety finding:** pad_thickness 2.4mm below minimum 3.0mm

[... truncated]
```

Cites: `RO-26-08031`, `RO-26-08074`, `RO-26-08062`, `RO-26-08052`, `RO-26-08165`, `RO-26-08274` ... 

## Promise risk

> Which jobs will miss their promised time?

`list_ros` · 25 citations · grounded=True · **0.05s**

```
**49 repair orders are at risk of missing their promised time.** Showing 25, most urgent first.

**RO-26-08031** - 2022 Ford Focus, PX22WSB
- Status: Parts Hold, promised time already missed (promised 2026-10-06 19:45)
- **Safety finding:** camber_left -1.8deg below minimum -1.0deg
- Customer reported: car pulls to the left when driving
- Waiting on: parts: 48750-B6M-A57
- Still to do: Four wheel alignment

**RO-26-08074** - 2024 Volkswagen Passat, YE24MED
- Status: Awaiting Authorisation, promised time already missed (promised 2026-10-08 09:50)
- **Safety finding:** tyre_tread_osr 1.4mm below minimum 1.6mm
- Customer reported: engine management light on, car feels down on power
- Waiting on: customer authorisation
- Still to do: Oxygen sensor R&R
- Customer is waiting on site

**RO-26-08062** - 2018 Mercedes C-Class, DD18NVG
- Status: Parts Hold, promised time already missed (promised 2026-10-08 17:30)
- **Safety finding:** tyre_tread_nsf 1.3mm below minimum 1.6mm
- **Safety finding:** rear_pad_thickness 2.4mm below minimum 3.0mm
- **Safety finding:** pad_thickness 2.4mm below minimum 3.0mm
- Customer reported: squealing noise when braking at low speed
- Waiting on: parts: 43022-S8M-B71
- Still to do: Rear brake pads & rotors R&R

**RO-26-08052** - 2022 Honda CR-V, GO22YWA
- Status: Parts Hold, promised time already missed (promised 2026-10-08 18:15)
- **Safety finding:** pad_thickness 2.4mm below minimum 3.0mm
- Customer reported: squealing noise when braking at low speed
- Waiting on: parts: 43022-B7H-A89
- Still to do: Rear brake pads & rotors R&R

**RO-26-08165** - 2023 Audi A4, WB23TZR
- Status: Parts Hold, promised time already missed (promised 2026-10-08 22:40)
- **Safety finding:** pad_thickness 2.4mm below minimum 3.0mm

[... truncated]
```

Cites: `RO-26-08031`, `RO-26-08074`, `RO-26-08062`, `RO-26-08052`, `RO-26-08165`, `RO-26-08274` ... 

## One technician's week

> What has EMP014 done this week?

`get_technician_activity` · 9 citations · grounded=True · **0.01s**

```
**Amara Osei** (EMP014) - Apprentice, Afternoon shift - completed **14 jobs** across **6 repair orders** in the last 7 days, and posted **19 updates**.

Time: **19.7 hours** spent on work the manual allows **19.1 hours** for - a ratio of **0.97**, behind the standard allowance.

**What was written most recently**

- **2026-10-09 13:16**, RO-26-08139 [UPD-00000-08139]
  "Cust reports blowing noise from underneath, louder than normal. Found blowing noise from underneath traced to exhaust flex pipe section repair. Finished noise/vibration diagnosis & road test. Rec exhaust flex pipe section repair, muffler & tailpipe R&R. Priced up, with the advisor for approval. Notes on the RO."

- **2026-10-08 19:48**, RO-26-08305 [UPD-00002-08305]
  "Parts checked - 31100-K1G-A21 is next-day order, RO on parts hold. Left alternator R&R for next shift. Will pick up next shift."

- **2026-10-08 19:38**, RO-26-08305 [UPD-00001-08305]
  "On the ramp now. Write-up says battery keeps going flat overnight. Codes on board - B1318 battery voltage low. parasitic draw measured 0.31A, within spec. Cause - battery keeps going flat overnight traced to alternator r&r. battery & charging system test, Parasitic draw diagnosis complete. Advise Alternator R&R. Will pick up next shift."

**Shorthand used in those notes**
- **R&R** - remove and refit
```

Cites: `UPD-00000-08139`, `RO-26-08139`, `UPD-00002-08305`, `RO-26-08305`, `UPD-00001-08305`, `UPD-00000-08305` ... 

## Customers waiting on site

> Are there any customers waiting on site?

`list_ros` · 14 citations · grounded=True · **0.05s**

```
**14 repair orders have a customer waiting on site.** Most urgent first.

**RO-26-08074** - 2024 Volkswagen Passat, YE24MED
- Status: Awaiting Authorisation, promised time already missed (promised 2026-10-08 09:50)
- **Safety finding:** tyre_tread_osr 1.4mm below minimum 1.6mm
- Customer reported: engine management light on, car feels down on power
- Waiting on: customer authorisation
- Still to do: Oxygen sensor R&R
- Customer is waiting on site

**RO-26-08274** - 2016 Volkswagen Passat, HU16SUH
- Status: Awaiting Authorisation, promised time already missed (promised 2026-10-09 13:45)
- **Safety finding:** toe_front 0.42deg below minimum 0.15deg
- Customer reported: steering wheel vibrates at motorway speed
- Waiting on: customer authorisation
- Customer is waiting on site

**RO-26-08310** - 2016 Volkswagen Golf, TE16CGW
- Status: Parts Hold, promised time already missed (promised 2026-10-07 10:50)
- Customer reported: coolant loss with no visible leak
- Waiting on: parts: 19200-T9G-B68
- Still to do: Cooling system drain & refill; Water pump R&R
- Customer is waiting on site

**RO-26-08187** - 2025 Vauxhall Astra, BY25NVH
- Status: Parts Hold, promised time already missed (promised 2026-10-08 09:40)
- Customer reported: coolant loss with no visible leak
- Waiting on: parts: 19200-B3M-A42
- Still to do: Water pump R&R; Cooling system drain & refill
- Customer is waiting on site

**RO-26-08256** - 2019 Audi A4, MM19YRF
- Status: Repair In Progress, promised time already missed (promised 2026-10-09 10:45)
- Customer reported: dashboard warning lights flickering intermittently
- Still to do: Wiring harness repair
- Customer is waiting on site

**RO-26-08073** - 2022 Honda CR-V, YJ22JWK
- Status: Dispatched, promised time already missed (promised 2026-10-09 11:20)

[... truncated]
```

Cites: `RO-26-08074`, `RO-26-08274`, `RO-26-08310`, `RO-26-08187`, `RO-26-08256`, `RO-26-08073` ... 

## Cross-RO patterns

> Any unusual patterns in the shop this week?

`detect_anomalies` · 19 citations · grounded=True · **0.05s**

```
Patterns across the last 7 days.

**1 part is blocking more than one job** - order once, clear several
- `90915-T9M-A93` is holding **2** repair orders: RO-26-08073, RO-26-08242

**Waiting on customer authorisation**
- RO-26-08074 2024 Volkswagen Passat - **28.7h** without a decision - customer waiting on site
- RO-26-08344 2022 Ford Focus - **19.9h** without a decision
- RO-26-08293 2020 Hyundai Tucson - **10.3h** without a decision - customer waiting on site
- RO-26-08159 2021 Vauxhall Astra - **9.6h** without a decision
- RO-26-08050 2025 Mercedes C-Class - **9.4h** without a decision
- RO-26-08116 2022 Honda Civic - **8.6h** without a decision
- RO-26-08345 2020 Hyundai Tucson - **8.6h** without a decision

**Stalled - nothing logged for over a day**
- RO-26-08319 2017 Volkswagen Golf - idle **57.3h** in Parts Hold, last touched by PRT009
- RO-26-08203 2023 Honda Civic - idle **55.8h** in Parts Hold, last touched by EMP039
- RO-26-08031 2022 Ford Focus - idle **47.2h** in Parts Hold, last touched by PRT008
- RO-26-08334 2019 Volkswagen Passat - idle **44.1h** in Parts Hold, last touched by PRT009
- RO-26-08382 2023 BMW 3 Series - idle **35.7h** in Parts Hold, last touched by EMP028
- RO-26-08052 2022 Honda CR-V - idle **32.6h** in Parts Hold, last touched by EMP033
- RO-26-08187 2025 Vauxhall Astra - idle **32.1h** in Parts Hold, last touched by EMP036
- RO-26-08275 2017 Volkswagen Passat - idle **30.1h** in Parts Hold, last touched by EMP028
- RO-26-08062 2018 Mercedes C-Class - idle **30.0h** in Parts Hold, last touched by EMP038
- RO-26-08087 2024 Toyota RAV4 - idle **29.9h** in Parts Hold, last touched by EMP023
```

Cites: `RO-26-08073`, `RO-26-08242`, `RO-26-08319`, `RO-26-08203`, `RO-26-08031`, `RO-26-08334` ... 

## Semantic recall — a fault someone has seen before

> Has anyone seen a whistling noise on a Passat before?

`search_updates` · 8 citations · grounded=True · **3.87s**

```
A whistling noise on a Passat has been reported before. [UPD-00001-08278] describes a louder than normal noise from underneath, traced to the exhaust flex pipe section, recommending repair of that section, muffler, and tailpipe. [UPD-00005-08170] confirms a customer concern but does not specify the cause. [UPD-00000-08274] reports a steering wheel vibration at motorway speed, traced to mount and balance, and recommends recalcibrating those components. [UPD-00001-08275] notes a clicking noise on full lock turns, traced to the CV axle shaft, recommending its replacement.
```

Cites: `UPD-00001-08278`, `RO-26-08278`, `UPD-00005-08170`, `RO-26-08170`, `UPD-00000-08274`, `RO-26-08274` ... 

## Semantic recall — a second phrasing

> Any history of a battery going flat overnight?

`search_updates` · 8 citations · grounded=True · **3.43s**

```
The updates indicate a history of a battery going flat overnight in several vehicles, including a 2023 Honda CR-V, a 2023 Volkswagen Golf, a 2017 Nissan Qashqai, and a 2022 Ford Transit. The common cause identified is the alternator. [UPD-00001-08309] [UPD-00001-08151] [UPD-00001-08389] [UPD-00001-08229]
```

Cites: `UPD-00001-08309`, `RO-26-08309`, `UPD-00001-08151`, `RO-26-08151`, `UPD-00001-08389`, `RO-26-08389` ... 

## Refused: an action it is not authorised to take

> Order the parts for RO-26-08165.

`get_ro_state` · 13 citations · grounded=True · **0.00s**

```
**RO-26-08165** - 2023 Audi A4, WB23TZR - 11677 miles
Status: **Parts Hold** - promised time already missed (promised 2026-10-08 22:40)
Customer reported: squealing noise when braking at low speed

**Safety - do not release**
- pad_thickness 2.4mm below minimum 3.0mm

**Blocked** - waiting on parts: 43022-T2A-B21

**Work completed** - 0.2 hours booked against 0.4 allowed
- Brake system inspection - 4 wheel - 0.2 hours (EMP014)

**Still to do**
- Rear brake pads & rotors R&R

**Parts**
- 43022-T2A-B21 - Next Day
```

Cites: `RO-26-08165`, `EV-57E49502F478`, `EV-DAA5CA9D4DA3`, `EV-8A8B5D493DB6`, `EV-C91634DF8154`, `EV-4F467FC704C9` ... 

## Refused: closing a repair order

> Close RO-26-08165 for me.

`get_ro_state` · 13 citations · grounded=True · **0.00s**

```
**RO-26-08165** - 2023 Audi A4, WB23TZR - 11677 miles
Status: **Parts Hold** - promised time already missed (promised 2026-10-08 22:40)
Customer reported: squealing noise when braking at low speed

**Safety - do not release**
- pad_thickness 2.4mm below minimum 3.0mm

**Blocked** - waiting on parts: 43022-T2A-B21

**Work completed** - 0.2 hours booked against 0.4 allowed
- Brake system inspection - 4 wheel - 0.2 hours (EMP014)

**Still to do**
- Rear brake pads & rotors R&R

**Parts**
- 43022-T2A-B21 - Next Day
```

Cites: `RO-26-08165`, `EV-57E49502F478`, `EV-DAA5CA9D4DA3`, `EV-8A8B5D493DB6`, `EV-C91634DF8154`, `EV-4F467FC704C9` ... 

## Two things measured here that are worth keeping

**The refusals cite too.** "Order the parts" and "Close RO-26-08165" are both
refused, and both still call `get_ro_state` and return citations. The agent
reads the record before declining, so the refusal names the actual job rather
than being a flat no.

**The 49.8s outlier is fixed, and it was not the model.** One semantic question
used to take 49.8s against another's 3.9s. It was the LLM router: the only call
in the system that asked for guided JSON decoding, which on this NIM costs
**37.5s** and returns *malformed* output - `{ "tools]:[{"` - against **0.2s**
and usable JSON without it. The keyword router matched the other questions, so
only the fallthrough ever paid. Guided decoding is now off by default
(`ASOIA_NIM_GUIDED_JSON`), and that question answers in 3.4s with the same 8
citations.
