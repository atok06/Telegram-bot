import logging
import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _detect_webhook_url() -> str:
    for env_name in ("WEBHOOK_URL", "RENDER_EXTERNAL_URL", "RAILWAY_PUBLIC_DOMAIN"):
        value = os.getenv(env_name, "").strip()
        if not value:
            continue
        if value.startswith("http://") or value.startswith("https://"):
            return value.rstrip("/")
        return "https://{0}".format(value.rstrip("/"))
    return ""


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini").strip() or "openai/gpt-4.1-mini"
OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions").strip() or "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_AI_PROVIDER = os.getenv("DEFAULT_AI_PROVIDER", "google").strip().lower() or "google"

WEBHOOK_URL = _detect_webhook_url()
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/telegram").strip() or "/telegram"
WEBHOOK_LISTEN = os.getenv("WEBHOOK_LISTEN", "0.0.0.0").strip() or "0.0.0.0"
WEBHOOK_PORT = _get_int("PORT", _get_int("WEBHOOK_PORT", 8080))

HH_API_BASE_URL = os.getenv("HH_API_BASE_URL", "https://api.hh.ru").strip() or "https://api.hh.ru"
BING_SEARCH_URL = os.getenv("BING_SEARCH_URL", "https://www.bing.com/search").strip() or "https://www.bing.com/search"
DEFAULT_COUNTRY_AREA_ID = os.getenv("DEFAULT_COUNTRY_AREA_ID", "40").strip() or "40"
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "20").strip() or "20")

JOB_RESULTS_LIMIT = max(3, min(_get_int("JOB_RESULTS_LIMIT", 5), 5))
PUBLIC_SEARCH_RESULTS_LIMIT = max(1, min(_get_int("PUBLIC_SEARCH_RESULTS_LIMIT", 3), 5))
ENABLE_PUBLIC_WEB_SEARCH = _get_bool("ENABLE_PUBLIC_WEB_SEARCH", True)
ENABLE_AI_ASSISTANT = _get_bool("ENABLE_AI_ASSISTANT", True)
AI_MAX_OUTPUT_TOKENS = max(200, min(_get_int("AI_MAX_OUTPUT_TOKENS", 500), 1000))


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
