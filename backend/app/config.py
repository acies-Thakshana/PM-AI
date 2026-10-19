"""Central config: env vars and file paths. No logic lives here."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
# PMAI_DATA_DIR relocates local-mode storage (sessions, profiles, audit log) -- used by tests.
DATA_DIR = Path(os.environ["PMAI_DATA_DIR"]) if os.getenv("PMAI_DATA_DIR") else BACKEND_DIR / "data"

# =====================================================================================
# AWS (DynamoDB)
#
# DynamoDB mode is on only when the docs table is configured (DDB_DOCS); otherwise
# everything falls back to local files under data/ so `uvicorn` on a laptop still works
# with no AWS resources. Table names come only from these env vars. No S3 for data: the
# DataFrames of a session stay in this process's memory (services/common/session_repo.py).
# =====================================================================================
AWS_REGION = os.getenv("AWS_REGION", "eu-north-1")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", AWS_REGION)
TRANSLATE_REGION = os.getenv("TRANSLATE_REGION", AWS_REGION)

DDB_DOCS = os.getenv("DDB_DOCS", "")          # partition session_id, sort doc
DDB_PROFILES = os.getenv("DDB_PROFILES", "")  # partition user_id, sort profile
DDB_AUDIT = os.getenv("DDB_AUDIT", "")        # partition session_id, sort ts_event; GSI by-user

USE_AWS_STORAGE = bool(DDB_DOCS)

# S3 holds only the two files the app produces for people to download: the outlier-comparison
# (change log) Excel and the finished report (.pptx). Everything else is DynamoDB / memory. With
# no bucket they are kept under data/sessions/<id>/files/ instead (local mode).
S3_BUCKET = os.getenv("S3_BUCKET", "")
# How many sessions' DataFrames one process keeps in memory before the least recently used go.
MEMORY_FRAME_SESSIONS = int(os.getenv("MEMORY_FRAME_SESSIONS", "50"))

# Sessions and their documents expire (DynamoDB TTL) this many days after last write.
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "30"))
AUDIT_LOG_TTL_DAYS = int(os.getenv("AUDIT_LOG_TTL_DAYS", "365"))

# Uploaded files go through the API (multipart).
UPLOAD_MAX_BYTES = int(os.getenv("UPLOAD_MAX_BYTES", str(200 * 1024 * 1024)))


# =====================================================================================
# SWP (SensiWatch) EXTERNAL API
#
# The trip data comes from this API instead of an uploaded file. Every secret (the two APIM
# subscription keys, the user name and password) lives only in the environment / backend/.env,
# never in code or in the browser.
# =====================================================================================
SWP_BASE_URL = os.getenv("SWP_BASE_URL", "").rstrip("/")
SWP_PROGRAM_ID = os.getenv("SWP_PROGRAM_ID", "")
SWP_SECURITY_KEY = os.getenv("SWP_SECURITY_KEY", "")   # APIM key for the token endpoint
SWP_TRIP_KEY = os.getenv("SWP_TRIP_KEY", "")           # APIM key for the trip endpoints
# The API returns temperatures in Fahrenheit; they are converted to Celsius (SWP_TEMPERATURE_FAHRENHEIT=0 if
# your program already returns Celsius).
SWP_TEMPERATURE_FAHRENHEIT = os.getenv("SWP_TEMPERATURE_FAHRENHEIT", "1") != "0"
# Keep what the API returned on disk (data/swp_cache): the trip list per program until it is refreshed, and the
# detail of ARRIVED trips for good. SWP_CACHE=0 always asks the API.
SWP_CACHE = os.getenv("SWP_CACHE", "1") != "0"
SWP_USER = os.getenv("SWP_USER", "")
SWP_PASS = os.getenv("SWP_PASS", "")
SWP_CLIENT_ID = os.getenv("SWP_CLIENT_ID", "common_client_jwt")
SWP_CLIENT_SECRET = os.getenv("SWP_CLIENT_SECRET", "secret")
# The API allows 20 calls a minute: wait this long after every call.
SWP_CALL_DELAY_SECONDS = float(os.getenv("SWP_CALL_DELAY_SECONDS", "2.5"))
# How long the fetched list of all trips is reused before it is fetched again.
SWP_TRIPS_CACHE_SECONDS = int(os.getenv("SWP_TRIPS_CACHE_SECONDS", "600"))
# Most trips one "Load" may pull in detail (each trip costs two API calls).
SWP_MAX_TRIPS = int(os.getenv("SWP_MAX_TRIPS", "50"))


# =====================================================================================
# MICROSOFT ENTRA ID
#
# Auth is enforced only when both ids are set. Unset (local dev) -> every request is the
# single user "local" and no token is needed.
# =====================================================================================
ENTRA_TENANT_ID = os.getenv("ENTRA_TENANT_ID", "")
ENTRA_CLIENT_ID = os.getenv("ENTRA_CLIENT_ID", "")
AUTH_ENABLED = bool(ENTRA_TENANT_ID and ENTRA_CLIENT_ID)
# Delegated scope a token must carry (the `scp` claim). Blocks app-only (client-credential)
# tokens and tokens issued for other APIs. Set to "" to skip the check.
ENTRA_REQUIRED_SCOPE = os.getenv("ENTRA_REQUIRED_SCOPE", "access_as_user")
# With AWS storage on, auth MUST be configured: otherwise every caller would be the single
# user "local" and could read everyone's sessions. Set ALLOW_ANON=1 to run open anyway
# (only sensible for a private demo).
ALLOW_ANON = os.getenv("ALLOW_ANON", "0") == "1"

# Comma-separated list of allowed browser origins, e.g. the Amplify URL.
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:5174,http://localhost:5175",
    ).split(",")
    if o.strip()
]
# Vite's dev server drifts to the next free port (5173 -> 5174 -> ...), so any localhost
# port is accepted too. Set CORS_ALLOW_LOCALHOST=0 in production to turn this off.
CORS_ALLOW_LOCALHOST = os.getenv("CORS_ALLOW_LOCALHOST", "1") != "0"

# =====================================================================================
# AMAZON BEDROCK
#
# BEDROCK_*_MODEL are Bedrock model ids or cross-region inference-profile ids (the "eu."
# prefix ones). The defaults below are PLACEHOLDERS for OpenAI's open-weight gpt-oss-20b, the
# lightest and cheapest model in the Stockholm catalog: copy the exact "Model ID" from the
# model's card in the Bedrock console (Model catalog) and set the env vars -- no code change.
# Other options: openai.gpt-oss-120b-1:0 (stronger), eu.amazon.nova-micro/lite/pro-v1:0.
# (Google Gemini and OpenAI's hosted GPT-4o-mini are NOT available on Bedrock.)
# =====================================================================================
# Three tiers; the cheapest setup uses the same small model for all of them. Point
# BEDROCK_STRONG_MODEL at a bigger model only if the planner / "think" / code-writing calls
# turn out unreliable.
BEDROCK_CHEAP_MODEL = os.getenv("BEDROCK_CHEAP_MODEL", "openai.gpt-oss-20b-1:0")
BEDROCK_DEFAULT_MODEL = os.getenv("BEDROCK_DEFAULT_MODEL", "openai.gpt-oss-20b-1:0")
BEDROCK_STRONG_MODEL = os.getenv("BEDROCK_STRONG_MODEL", "openai.gpt-oss-20b-1:0")

# Amazon Nova models cap the answer length per call (about 5K tokens). A request above the cap
# is rejected, so llm.py lowers max_tokens to this for any "amazon.nova" model id.
NOVA_MAX_OUTPUT_TOKENS = int(os.getenv("NOVA_MAX_OUTPUT_TOKENS", "5000"))

# The older per-agent settings are kept as the `legacy` fallback that `model_for()` takes.
LLM_MODEL = os.getenv("LLM_MODEL", BEDROCK_DEFAULT_MODEL)
FEATURE_AGENT_MODEL = os.getenv("FEATURE_AGENT_MODEL", BEDROCK_DEFAULT_MODEL)
ANALYSIS_AGENT_MODEL = os.getenv("ANALYSIS_AGENT_MODEL", BEDROCK_DEFAULT_MODEL)
DRILLDOWN_AGENT_MODEL = os.getenv("DRILLDOWN_AGENT_MODEL", BEDROCK_STRONG_MODEL)
PLANNER_AGENT_MODEL = os.getenv("PLANNER_AGENT_MODEL", BEDROCK_STRONG_MODEL)

# Bedrock Prompt Management: JSON object mapping a prompt name (the call_name, e.g.
# "planner_agent") to "<PROMPT_ID>" or "<PROMPT_ID>:<VERSION>". The system prompts no longer
# live in the Python code. Each call gets its prompt from Bedrock when its name is listed here;
# otherwise from backend/prompts/<name>.txt (shipped only in a dev checkout -- the Docker image
# does NOT contain them, so a deployed backend needs every prompt listed here).
BEDROCK_PROMPT_IDS = os.getenv("BEDROCK_PROMPT_IDS", "")
# Where the default prompt files are. PROMPTS_BEDROCK_ONLY=1 ignores them entirely, so a
# prompt missing from Bedrock fails loudly instead of silently using a local copy.
PROMPTS_DIR = Path(os.environ["PROMPTS_DIR"]) if os.getenv("PROMPTS_DIR") else BACKEND_DIR / "prompts"
PROMPTS_BEDROCK_ONLY = os.getenv("PROMPTS_BEDROCK_ONLY", "0") == "1"
PROMPT_CACHE_SECONDS = int(os.getenv("PROMPT_CACHE_SECONDS", "300"))


# Groq (OpenAI-compatible API) for the calls named in GROQ_CALLS (default "*": every LLM call, while there
# are no AWS credentials). Needs GROQ_API_KEY. GROQ_CALLS="planner_agent,audit_agent" limits it to those
# calls (the rest stay on Bedrock); GROQ_CALLS="" turns it off.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "") or "llama-3.3-70b-versatile"
GROQ_CALLS = {c.strip() for c in os.getenv("GROQ_CALLS", "*").split(",") if c.strip()}


def uses_groq(call_name: str) -> bool:
    return bool(GROQ_API_KEY) and ("*" in GROQ_CALLS or call_name in GROQ_CALLS)


# =====================================================================================
# MODEL PER LLM CALL
#
# Every LLM call has a name (its `call_name`, also what the audit log records).
# MODEL_BY_CALL gives each call its own model, so the heavy-reasoning calls can use a
# stronger model than the cheap, high-volume ones.
#
# Trying one call: set MODEL_<CALL NAME IN CAPITALS> in the environment, e.g.
#   MODEL_ANALYSIS_AGENT_INTERPRET=eu.anthropic.claude-sonnet-4-5-20250929-v1:0
# USE_PER_CALL_MODELS=0 ignores this whole table and uses the per-agent settings above.
# =====================================================================================
# Longest answer any LLM call may produce. Every call sets a limit; raise this only if
# answers get cut off.
DEFAULT_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "6000"))

USE_PER_CALL_MODELS = os.getenv("USE_PER_CALL_MODELS", "1") != "0"

_C = BEDROCK_CHEAP_MODEL
_D = BEDROCK_DEFAULT_MODEL
_S = BEDROCK_STRONG_MODEL

MODEL_BY_CALL: dict[str, str] = {
    # -- Planner and drill-down path design: reasoning that decides what gets built ----------
    "planner_agent": _S,
    "drilldown_path": _S,

    # -- Feature agent: think = designs the formula, write_code = pandas, validate = checks ---
    "feature_agent_think": _S,
    "feature_agent_write_code": _D,
    "feature_agent_validate": _D,
    "feature_suggester": _D,

    # -- Analysis agent ----------------------------------------------------------------------
    "analysis_agent_think": _S,
    "analysis_agent_write_code": _D,
    "analysis_agent_chart_suggestion": _D,
    "analysis_agent_interpret": _C,
    "analysis_agent_drilldown": _D,

    # -- Analysis designer (custom analyses, template matching) ------------------------------
    "analysis_designer_template_match": _S,
    "analysis_designer_chart": _D,
    "analysis_suggester": _D,

    # -- Drill-down suggestions --------------------------------------------------------------
    "drilldown_agent": _D,
    "drilldown_agent_more": _D,

    # -- Summaries -----------------------------------------------------------------------------
    "audit_agent": _C,
    "overall_analysis_agent": _C,
    "report_final_summary_agent": _C,
}


def model_for(call_name: str, legacy: str) -> str:
    """The model for one LLM call: an env override (MODEL_<CALL_NAME>) wins, then the
    table above, then `legacy` -- the older per-agent setting -- for calls not in the
    table or when USE_PER_CALL_MODELS=0 (but an env override still applies)."""
    override = os.getenv("MODEL_" + call_name.upper())
    if override:
        return override
    if USE_PER_CALL_MODELS and call_name in MODEL_BY_CALL:
        return MODEL_BY_CALL[call_name]
    return legacy
