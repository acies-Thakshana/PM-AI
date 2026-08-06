"""Central config: env vars and file paths. No logic lives here."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
REPORTS_DIR = APP_DIR.parent / "generated_reports"
REPORTS_DIR.mkdir(exist_ok=True)

EXCEL_PATH = DATA_DIR / "cold_chain_metrics.xlsx"
KNOWLEDGE_PATH = DATA_DIR / "post_harvest_knowledge.md"
CHOCOLATE_KNOWLEDGE_PATH = DATA_DIR / "chocolate_cold_chain_knowledge.md"

# Phase 2: simulated multi-source uploads (SensiWatch, ColdStream, customer
# profile, business rules) -- see scripts/simulate_all_data.py
SIMULATED_DATA_DIR = DATA_DIR / "simulated"
SIMULATED_DATA_DIR.mkdir(exist_ok=True)
SENSIWATCH_SAMPLE_PATH = SIMULATED_DATA_DIR / "sensiwatch_export.xlsx"
COLDSTREAM_SAMPLE_PATH = SIMULATED_DATA_DIR / "coldstream_export.xlsx"
CUSTOMER_PROFILE_SAMPLE_PATH = SIMULATED_DATA_DIR / "belvoire_customer_profile.md"
BUSINESS_RULES_SAMPLE_PATH = SIMULATED_DATA_DIR / "business_rules_and_kpis.json"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

PROGRAM_NAME = "Cold Chain Post-Harvest Assessment Program"
