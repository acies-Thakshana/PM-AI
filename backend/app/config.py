"""Central config: env vars and file paths. No logic lives here."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
DATA_DIR = BACKEND_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"

# Optional -- report translation only (see translation_service.py). A report
# download still succeeds without this set; it just stays in English.
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY", "")

# Optional -- the audit/analysis summary narratives only (see audit_summary.py
# and overall_narrative.py). Without this set, both fall back to their own
# deterministic, rule-based sentence -- nothing else in the app depends on it.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://pm-ai-frontend-thakshana.s3-website.eu-north-1.amazonaws.com",
]
