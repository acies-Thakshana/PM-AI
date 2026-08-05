# Post-Harvest Cold Chain Technical Knowledge Base

This document is the domain-knowledge reference for the Cold Chain / Post-Harvest
Assessment Program. It is unstructured technical guidance (not raw data) used to
interpret sensor and quality data with expert-level reasoning — e.g. connecting a
temperature excursion to a specific green-life loss and a specific likely cause.

## 1. Core Principles

### 1.1 Respiration Rate and the Q10 Rule
Fresh produce continues to respire after harvest, consuming stored sugars and
releasing heat, CO2, and moisture. Respiration rate roughly follows the Q10 rule:
**for every 10C rise in product temperature, respiration rate increases by a factor
of 2 to 3**. Higher respiration accelerates senescence (ripening/aging), directly
shortening shelf life ("green life"). This is why even short excursions above the
target temperature band compound quickly — a 5C excursion is not "5C of stress",
it can be closer to 1.5-2x the normal aging rate for the duration of the excursion.

### 1.2 Cumulative Time-Temperature Exposure ("Degree-Hours")
The standard way to quantify cold chain stress is **degree-hours above target
max** = sum over all readings of (measured temp - target max C) x (hours between
readings), counting only readings above the target max. This is more predictive
of quality loss than peak temperature alone, because sustained moderate excursions
can do as much damage as brief severe ones.

Rule-of-thumb sensitivity (spoilage % per degree-hour above target max, before
other factors): chilling-sensitive tropical/subtropical fruit (mango, banana,
tomato) ~0.45-0.65% per degree-hour; highly perishable leafy greens and berries
(spinach, strawberry) ~0.9-1.1% per degree-hour, because their thin tissue and
high surface-area-to-volume ratio give almost no thermal buffering.

A shipment with **more than ~15 degree-hours** of cumulative excursion should be
treated as high-risk regardless of commodity; above ~25 degree-hours, expect
double-digit spoilage percentages and rejection-level quality loss.

### 1.3 Chilling Injury vs. Heat-Driven Spoilage
Produce falls into two distinct risk categories and the corrective action is
different for each:
- **Chilling-sensitive** (mango, banana, tomato): damaged by temperatures *below*
  their target minimum, not just above the max. Symptoms: internal browning,
  pitting, surface scald, failure to ripen normally, off-flavors. Chilling injury
  is often not visible until days after exposure ("delayed symptom expression"),
  which is why time-temperature logs are more reliable than a visual inspection
  at time of delivery.
- **Non-chilling-sensitive / near-freezing-tolerant** (leafy greens, berries):
  actually benefit from being held near 0C and are instead damaged by
  temperatures rising *above* their (very narrow) target band. Symptoms: wilting,
  yellowing, rapid softening, mold/decay onset. These commodities have almost no
  safety margin — even 2-3C above target for a few hours materially shortens
  shelf life.

### 1.4 Humidity and Door-Open Events
Reefer door openings (at checkpoints, transfers, inspections) cause a rapid,
short-lived temperature spike and a simultaneous **humidity drop** as cold,
moist air is displaced by warm, dry ambient air. Humidity drops accelerate
moisture loss (wilting, shriveling) independent of the temperature effect.
More than 2 door-open events on a single transit leg is a strong leading
indicator of both temperature and humidity non-compliance, and frequently
correlates with fresh-appearing produce that still shows accelerated water
loss on arrival.

## 2. Commodity-Specific Reference Profiles

### 2.1 Alphonso Mango
- Target: 10-13C, 85-90% RH. Chilling-sensitive.
- Base green life at optimal storage: ~14 days.
- Below 10C for extended periods: internal browning, uneven/failed ripening,
  "black tip" discoloration. Above 13C: accelerated ripening, softening,
  shortened marketable window.
- Excursion sensitivity: ~0.55% spoilage per degree-hour above target max.

### 2.2 Roma Tomato (mature-green/breaker stage)
- Target: 12-15C, 90-95% RH. Chilling-sensitive.
- Base green life: ~14 days.
- Below 12C: pitting, surface scald, poor/blotchy color development, increased
  decay after chilling exposure even if not visible immediately.
- Excursion sensitivity: ~0.45% spoilage per degree-hour above target max.

### 2.3 Cavendish Banana
- Target: 13-14.5C, 90-95% RH. Highly chilling-sensitive — the narrowest safe
  band of the tropical fruits in this program.
- Base green life: ~10 days.
- Below 12C even briefly: dull/grey peel discoloration, failure to ripen
  ("green ripe" defect), taste degradation. Requires the tightest transit
  compliance of the commodities handled.
- Excursion sensitivity: ~0.65% spoilage per degree-hour above target max.

### 2.4 Baby Spinach (leafy green)
- Target: 0-4C, 95-100% RH. NOT chilling-sensitive — wants to be as close to 0C
  as possible without freezing.
- Base green life: ~7 days (very short — highest respiration rate of the
  commodities in this program).
- Above 4C: rapid wilting, yellowing (chlorophyll breakdown), decay onset within
  hours of sustained exposure.
- Excursion sensitivity: ~0.9% spoilage per degree-hour above target max —
  among the least forgiving commodities in the program.

### 2.5 Strawberry
- Target: 0-2C, 90-95% RH. NOT chilling-sensitive.
- Base green life: ~5 days — the shortest in the program and the least tolerant
  of any handling delay or temperature deviation.
- Above 2C: softening, rapid mold/Botrytis onset, juice leakage. Strawberries
  effectively have no thermal buffer; a few degree-hours above target can move
  a shipment from sellable to reject-grade.
- Excursion sensitivity: ~1.1% spoilage per degree-hour above target max —
  highest in the program; treat any sustained excursion as high-priority.

## 3. Common Cold Chain Failure Modes

1. **Aging/under-maintained refrigeration plant.** Facilities running ammonia
   screw compressors or split units installed before ~2015, especially without
   maintenance in the preceding 6 months, show materially higher rates of
   temperature excursions during dwell time — the compressor cycles more slowly
   and struggles to recover after door-open events. This is a facility/equipment
   root cause, not a produce or handling root cause, and points to a
   maintenance/capex recommendation rather than a process one.
2. **Pre-cooling delays.** Produce loaded into a reefer without being pre-cooled
   to target temperature first forces the in-transit unit to remove field heat
   during transit, causing an excursion in the first hours of the trip that
   shows up as elevated readings clustered near the "Origin Loading Bay"
   checkpoint.
3. **Excessive door-open events.** Each additional stop/transfer/checkpoint
   inspection adds a temperature spike and humidity drop; routes with more than
   2 door-open events consistently show worse arrival quality than routes with
   0-1, independent of total transit time.
4. **Long-haul thermal fatigue.** On routes over ~800km / 18+ hours, reefer
   units run continuously for longer, increasing the chance of a mid-transit
   excursion as the compressor works through a full day-night ambient cycle.
5. **Compressor/refrigerant type mismatch with route profile.** Facilities using
   older ammonia (NH3) screw compressor systems generally have coarser
   temperature control (wider swing) than newer R404A multi-compressor rack
   systems, which modulate more precisely — this shows up as noisier sensor
   traces and more frequent brief excursions even without a single dramatic
   failure event.

## 4. Corrective Action Catalog

Use these when writing recommendations — match the action to the diagnosed root
cause, don't default to generic "improve monitoring" language.

- **Facility refrigeration upgrade/retrofit**: for facilities with pre-2015
  installs and repeat excursion patterns across multiple shipments — points to
  a capex/maintenance recommendation at the facility level.
- **Preventive maintenance scheduling**: for facilities with >6 months since
  last recorded maintenance and above-average excursion rates — lower-cost fix
  than a full retrofit, appropriate when the equipment is newer but neglected.
- **Pre-cooling protocol enforcement**: when excursions cluster at the start of
  transit (origin checkpoint) — a process/SOP fix, not an equipment fix.
- **Checkpoint/transfer consolidation**: when door-open event counts are high
  and correlate with quality loss — reduce the number of transfer points or
  batch inspections to cut cumulative door-open exposure.
- **Route/commodity re-pairing**: for highly sensitive commodities (spinach,
  strawberry) currently routed through long-haul (>800km) legs or older
  facilities — pair the most sensitive commodities with the shortest routes and
  newest facilities first.
- **Driver/handler retraining**: when door-open counts are high but not
  explained by route complexity — suggests avoidable/discretionary stops.

## 5. Program KPI Interpretation Guide

- **Temperature Compliance Rate** (target: 95%): share of sensor readings inside
  the commodity's target band. Below target signals systemic (not one-off)
  cold chain issues and should be the headline metric in an executive summary.
- **Maximum Acceptable Spoilage** (target: ceiling 8%): shipments above this
  should be individually named and root-caused in the report, not averaged away.
- **Minimum Green Life Retention** (target: 70% of base shelf life remaining at
  arrival): this is the metric that ties cold chain performance directly to
  commercial value — lost green life is lost sellable window and lost price
  realization for the grower/distributor.
- **Door-Open Events per Shipment** (target: max 2): a leading/process indicator
  that predicts quality issues before they show up in spoilage numbers, useful
  for forward-looking recommendations rather than only historical reporting.
