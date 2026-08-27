"""Central config: env vars and file paths. No logic lives here."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
DATA_DIR = BACKEND_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Dataiku DSS integration
DATAIKU_ENABLED = os.getenv("DATAIKU_ENABLED", "false").lower() == "true"
DATAIKU_DSS_URL = os.getenv("DATAIKU_DSS_URL", "")
DATAIKU_API_KEY = os.getenv("DATAIKU_API_KEY", "")
DATAIKU_PROJECT_KEY = os.getenv("DATAIKU_PROJECT_KEY", "PM_AI")
DATAIKU_UPLOADS_FOLDER_ID = os.getenv("DATAIKU_UPLOADS_FOLDER_ID", "DYogvtm1")
DATAIKU_AUDIT_SCENARIO_ID = os.getenv("DATAIKU_AUDIT_SCENARIO_ID", "")

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
]
