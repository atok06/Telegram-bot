import logging
import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get_first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _normalize_public_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value.lstrip('/')}"
    return value


def _get_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value not in {"0", "false", "no", "off"}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "xiaomi/mimo-v2-omni").strip()
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DUCKDUCKGO_API_URL = "https://api.duckduckgo.com/"
WEBHOOK_URL = _normalize_public_url(
    _get_first_env(
        "WEBHOOK_URL",
        "APP_URL",
        "RENDER_EXTERNAL_URL",
        "RAILWAY_STATIC_URL",
        "RAILWAY_PUBLIC_DOMAIN",
        "KOYEB_PUBLIC_DOMAIN",
    )
)
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/telegram").strip() or "/telegram"
WEBHOOK_LISTEN = os.getenv("WEBHOOK_LISTEN", "0.0.0.0").strip() or "0.0.0.0"
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", os.getenv("PORT", "8080")).strip())
AI_MEMORY_MESSAGES = max(0, int(os.getenv("AI_MEMORY_MESSAGES", "8").strip() or "8"))
ENABLE_WEB_SEARCH = _get_bool_env("ENABLE_WEB_SEARCH", True)
WEB_SEARCH_RESULTS_LIMIT = max(1, int(os.getenv("WEB_SEARCH_RESULTS_LIMIT", "5").strip() or "5"))
AI_SYSTEM_PROMPT = (
    "You are a helpful assistant for a Telegram bot. "
    "Reply in the same language as the user. "
    "Use prior conversation context when it is relevant. "
    "If web search snippets are provided, use them for time-sensitive facts and mention uncertainty when needed. "
    "Keep answers practical and concise."
)


def configure_logging() -> None:
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
