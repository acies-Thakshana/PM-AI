"""
Simulates the machine-readable business rules / thresholds / KPI catalog a PM
would apply to a customer's data (items 4 and 5 from the ask: predefined
business rules + abnormal-value thresholds, and standard + customer-specific
KPIs, combined into one config since both are "rules data" rather than raw
shipment data).
"""

CONTENT = {
    "customer": "Belvoire Chocolatier",
    "product_specs": {
        "Dark Chocolate Couverture 70%": {
            "temp_min_c": 15.0, "temp_max_c": 18.0,
            "humidity_min_pct": 30, "humidity_max_pct": 55,
            "quality_risk_note": "Fat bloom risk above 24C sustained exposure",
        },
        "Milk Chocolate Pralines": {
            "temp_min_c": 16.0, "temp_max_c": 18.0,
            "humidity_min_pct": 30, "humidity_max_pct": 50,
            "quality_risk_note": "Sugar bloom risk if humidity exceeds spec for multiple hours (condensation on cooling)",
        },
        "Cocoa Butter Blocks": {
            "temp_min_c": 16.0, "temp_max_c": 20.0,
            "humidity_min_pct": 30, "humidity_max_pct": 60,
            "quality_risk_note": "Softening / partial melt risk above 28C",
        },
    },
    "anomaly_thresholds": {
        "sensiwatch_stuck_trip_days_since_creation": 14,
        "sensiwatch_gps_arrival_radius_km": 5,
        "coldstream_min_trip_duration_days": 0.25,
        "coldstream_max_trip_duration_days": 21,
        "temp_sane_min_c": -10,
        "temp_sane_max_c": 60,
        "humidity_sane_min_pct": 0,
        "humidity_sane_max_pct": 100,
    },
    "standard_kpis": [
        {"name": "% Time In Spec", "description": "Share of transit time within the product's target temperature band",
         "target_pct": 95},
        {"name": "Excursion Events", "description": "Count of sustained out-of-spec temperature periods per trip",
         "target_max": 1},
        {"name": "Trip Closure Rate", "description": "Share of trips correctly closed with an arrival date within 48h of actual delivery",
         "target_pct": 98},
    ],
    "customer_kpis": [
        {"name": "Bloom Risk Score", "description": "Composite 0-100 score combining time-above-threshold and humidity excursions, weighted by product bloom sensitivity",
         "target_max": 15},
    ],
}
