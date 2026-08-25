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

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
]
