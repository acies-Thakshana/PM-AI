export const FLAG_LABELS: Record<string, string> = {
  active: "Active - in transit",
  closed: "Closed",
  clean: "Clean",
  likely_arrived: "Likely arrived - should be closed",
  stuck_unresolved: "Stuck - needs investigation",
  duration_too_short: "Duration too short",
  duration_too_long: "Duration too long",
  missing_end_date: "Missing end date",
  value_outlier: "Value outlier",
};

export const FLAG_SEVERITY: Record<string, "ok" | "warn" | "bad"> = {
  active: "ok",
  closed: "ok",
  clean: "ok",
  likely_arrived: "warn",
  stuck_unresolved: "bad",
  duration_too_short: "bad",
  duration_too_long: "bad",
  missing_end_date: "bad",
  value_outlier: "bad",
};

// mirrors app/services/trip_analytics.py FLAG_INFO -- presentation copy only
export const FLAG_DESCRIPTIONS: Record<string, string> = {
  active: "Genuinely still en route - within normal transit time for this lane.",
  closed: "Trip was closed with an arrival date on record.",
  clean: "No data-quality issues detected.",
  likely_arrived:
    "Trip still shows 'In Transit' but GPS position (or a customer delivery confirmation) indicates the " +
    "shipment has arrived. Needs to be closed manually so it is picked up correctly in reporting.",
  stuck_unresolved:
    "Trip is overdue for arrival and the last GPS reading is not near the destination coordinates. Worth " +
    "investigating for a structural cause (routing, customs delay, wrong destination configuration) before closing.",
  duration_too_short:
    "Trip duration is implausibly short (near-zero) - most likely a start/end date entry mistake rather than a " +
    "real shipment.",
  duration_too_long:
    "Trip duration is implausibly long with no end date recorded - the record was never properly closed out.",
  missing_end_date: "Trip has no end date recorded, so duration and compliance can't be reliably calculated.",
  value_outlier:
    "One or more readings fall outside physically plausible bounds - most likely a sensor glitch rather than a " +
    "real temperature/humidity excursion.",
};
