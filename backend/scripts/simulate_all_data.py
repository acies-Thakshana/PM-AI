"""
Generates all 4 simulated data sources for the Belvoire Chocolatier demo
customer: SensiWatch export, ColdStream export, customer profile doc, and the
business rules/KPI config. Run once (or whenever you want fresh sample data):

    python scripts/simulate_all_data.py

Each source has its own simulator module in scripts/simulators/ so they stay
independently testable; this script only wires them together and writes files.
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import (  # noqa: E402
    BUSINESS_RULES_SAMPLE_PATH,
    COLDSTREAM_SAMPLE_PATH,
    CUSTOMER_PROFILE_SAMPLE_PATH,
    SENSIWATCH_SAMPLE_PATH,
)
from scripts.simulators import (  # noqa: E402
    business_rules_simulator,
    coldstream_simulator,
    customer_profile_simulator,
    sensiwatch_simulator,
)


def _write_workbook(path, sheets: dict[str, pd.DataFrame]):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)


def main():
    sensiwatch_sheets = sensiwatch_simulator.generate()
    _write_workbook(SENSIWATCH_SAMPLE_PATH, sensiwatch_sheets)
    print(f"Wrote {SENSIWATCH_SAMPLE_PATH}")
    print(f"  Trip_Header: {len(sensiwatch_sheets['Trip_Header'])} trips")
    print(f"  Sensor_Readings: {len(sensiwatch_sheets['Sensor_Readings'])} rows")

    coldstream_sheets = coldstream_simulator.generate()
    _write_workbook(COLDSTREAM_SAMPLE_PATH, coldstream_sheets)
    print(f"Wrote {COLDSTREAM_SAMPLE_PATH}")
    print(f"  Trip_Header: {len(coldstream_sheets['Trip_Header'])} trips")
    print(f"  Sensor_Readings: {len(coldstream_sheets['Sensor_Readings'])} rows")

    CUSTOMER_PROFILE_SAMPLE_PATH.write_text(customer_profile_simulator.CONTENT, encoding="utf-8")
    print(f"Wrote {CUSTOMER_PROFILE_SAMPLE_PATH}")

    BUSINESS_RULES_SAMPLE_PATH.write_text(
        json.dumps(business_rules_simulator.CONTENT, indent=2), encoding="utf-8"
    )
    print(f"Wrote {BUSINESS_RULES_SAMPLE_PATH}")


if __name__ == "__main__":
    main()
