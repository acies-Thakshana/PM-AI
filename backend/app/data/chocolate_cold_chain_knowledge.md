# Chocolate Cold Chain Technical Knowledge Base

This document is the domain-knowledge reference for the Belvoire Chocolatier cold
chain program. It is unstructured technical guidance (not raw data) used to
interpret trip/sensor data with expert-level reasoning -- e.g. connecting a
temperature or humidity excursion to a specific bloom risk, and connecting a
trip-triage flag to a specific operational root cause.

## 1. Core Principles

### 1.1 Fat Bloom
Fat bloom is caused by sustained exposure above a product's upper temperature
threshold: cocoa butter crystals partially melt and migrate to the surface,
then re-solidify in an unstable polymorphic form. The result is a dull,
greyish-white streaky or blotchy film on the surface. It is a cosmetic/quality
defect, not a food-safety one, but it is highly visible and drives commercial
rejection -- retailers and quality teams treat it as a hard reject, not a
minor deviation. Products with higher cocoa-butter content (dark couverture,
raw cocoa butter blocks) are more fat-bloom-prone than milk chocolate, which
has more milk fat diluting the effect but a correspondingly narrower safe
band before other defects set in.

### 1.2 Sugar Bloom
Sugar bloom is primarily humidity-driven, not temperature-driven: moisture
condenses on the chocolate surface (most often when a cold product is moved
into a warmer, humid environment, or when in-transit humidity sustained above
the target band for multiple hours), dissolving surface sugar; when the
moisture later evaporates, the sugar recrystallizes into a rough, gritty white
coating. Because it is triggered by *humidity*, a trip can be fully compliant
on temperature and still show sugar bloom risk -- humidity compliance must be
assessed independently of temperature compliance, not inferred from it.

### 1.3 Cumulative Exposure vs. Single Excursions
Bloom risk compounds with sustained exposure, not a single brief spike --
this is why the program's primary compliance metric is **% Time In Spec**
(share of transit time within target band) rather than a simple pass/fail on
peak temperature. A trip with one 10-minute spike but otherwise clean data is
materially lower risk than a trip with a moderate, sustained excursion across
several hours, even if the moderate excursion never reaches as high a peak.
The **Bloom Risk Score** (0-100, target <= 15) is the composite metric that
captures this: it combines the temperature-excursion share and the
humidity-excursion share, weighted toward temperature as the dominant driver
of fat bloom (the more commercially severe defect) while still counting
humidity/sugar-bloom risk.

### 1.4 Data Triage Is a Distinct Risk Category
Unlike a pure product-quality problem, a large share of this program's
findings are *operational/process* issues that never touch the product at
all, but corrupt the reporting basis a Program Manager relies on:
- **SensiWatch trips never manually closed.** SensiWatch is a real-time
  platform -- a trip only carries "In Transit" from the device feed itself;
  someone has to manually set it to closed/arrived. A trip that is overdue
  and whose last known GPS position sits at (or very near) the destination
  coordinates has, in practice, arrived -- it just was not closed out. This
  should be flagged as a closure-process gap, not a live delivery problem.
- **Genuinely stalled trips.** A trip that is overdue AND whose GPS position
  is nowhere near the destination is a real structural issue -- a routing
  problem, a customs/border hold, or a misconfigured destination address --
  and should be escalated rather than assumed to be a closure oversight.
- **ColdStream data-quality outliers.** Implausibly short (~0 days) or long
  (many weeks with no end date) trip durations are almost always a data-entry
  mistake or a record that was never closed out, not a real shipment.
  Physically impossible sensor values (e.g. -40C or +95C for a chocolate
  shipment) indicate a sensor/logger glitch, not a real excursion. Both
  should be excluded from compliance scoring once confirmed, but the
  underlying device/process should still be flagged for a fix so the same
  gap doesn't recur next reporting cycle.

## 2. Product-Specific Reference Profiles

### 2.1 Dark Chocolate Couverture 70%
- Target: 15-18C, 30-55% RH.
- Fat bloom risk above 24C sustained exposure. High cocoa-butter content
  (70%) makes this the most temperature-sensitive product in the range --
  narrower effective safety margin than the milk chocolate or raw cocoa
  butter products, even though its nominal target band looks similar.

### 2.2 Milk Chocolate Pralines
- Target: 16-18C, 30-50% RH.
- Sugar bloom risk if humidity exceeds spec for multiple hours (condensation
  on cooling). As a filled confection (nut pastes, creams), moisture
  migration from the filling toward the shell adds an additional
  humidity-sensitivity pathway beyond the shell chocolate itself -- humidity
  compliance matters even more here than for solid-format products.

### 2.3 Cocoa Butter Blocks
- Target: 16-20C, 30-60% RH.
- Softening / partial melt risk above 28C. As a raw ingredient block rather
  than a finished confection, the primary risk is physical deformation and
  re-solidification with an altered (softer, greasier) crystal structure --
  this affects downstream processability for the customer's own production,
  not just cosmetic appearance.

## 3. Common Cold Chain Failure Modes

1. **Never-closed SensiWatch trips.** The single highest-volume finding
   pattern in this program: trips overdue for arrival where the last GPS
   reading sits within a small radius of the destination coordinates. Treat
   as a closure-process gap; cross-check against any customer delivery
   confirmation available before reporting it as resolved.
2. **Genuinely stalled trips.** Overdue AND GPS far from destination --
   escalate as a real structural issue (routing, customs, configuration),
   don't just close it out.
3. **Warm-humid transshipment dwell time.** The highest-risk moment for both
   fat bloom (a short heat spike) and sugar bloom (condensation as the
   product cools back down afterward) is often a transfer/cross-dock leg
   that isn't refrigerated, even when the trip's overall average looks
   compliant -- aggregate compliance percentages can hide a short, severe
   dwell-time excursion.
4. **Humidity control loss independent of temperature control.** Many reefer
   units hold temperature far more tightly than humidity. A lane or product
   can be fully temperature-compliant and still carry real sugar-bloom risk
   -- always check humidity compliance as its own number, not as implied by
   temperature performance.
5. **ColdStream logger/data-entry errors.** Implausible trip durations or
   sensor values are a device/process fix (logger calibration, data-entry
   review), not a cold-chain event -- but recurring instances on the same
   lane or device are themselves worth flagging as a pattern.

## 4. Corrective Action Catalog

Use these when writing recommendations -- match the action to the diagnosed
root cause, don't default to generic "improve monitoring" language.

- **Trip closure SOP / automated GPS-arrival auto-close**: for repeat
  "likely arrived, should be closed" patterns on SensiWatch -- a process fix
  that removes manual review overhead, not a cold-chain fix.
- **Escalation protocol for stalled trips**: for genuinely stuck/unresolved
  trips -- route to the account or carrier team for investigation rather
  than treating as a closure oversight.
- **ColdStream logger firmware/calibration review**: for repeat
  duration/value-outlier data-quality flags concentrated on the same device
  or lane.
- **Insulated/refrigerated handling for transshipment legs**: for lanes
  where a transfer/dwell point correlates with bloom-risk spikes even though
  overall trip compliance looks acceptable.
- **Humidity-controlled reefer settings review**: for lanes or products
  showing good temperature compliance but weaker humidity compliance.
- **Route/lane consolidation for high bloom-risk products**: pair the most
  sensitive products (Dark Chocolate Couverture, given its narrower
  effective margin) with the shortest, most reliable lanes and the
  best-performing carriers first.

## 5. Program KPI Interpretation Guide

- **% Time In Spec** (target: 95%): share of transit time within the
  product's target temperature band. Should be reported for temperature and
  humidity separately, since they can diverge.
- **Excursion Events** (target: max 1 per trip): count of sustained
  out-of-spec temperature periods per trip -- a leading indicator of process
  issues even on trips whose average compliance still looks acceptable.
- **Trip Closure Rate** (target: 98%): share of trips correctly closed with
  an arrival date within 48h of actual delivery -- a process KPI as much as
  a product KPI, and the metric most directly tied to the "should be closed"
  / "stuck" triage findings.
- **Bloom Risk Score** (target: <= 15): composite 0-100 score combining
  temperature and humidity excursion share, weighted toward temperature as
  the dominant driver of the more commercially severe fat-bloom defect --
  the single number that best predicts commercial rejection risk for a given
  lane/product.
