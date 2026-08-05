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

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

PROGRAM_NAME = "Cold Chain Post-Harvest Assessment Program"
