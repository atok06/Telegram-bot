import logging  # Лог хабарламаларын басқару кітапханасы
import os  # Орта айнымалыларын оқу үшін
from pathlib import Path  # Файл жолдарымен жұмыс жасау үшін

from dotenv import load_dotenv  # .env файлынан айнымалыларды жүктеу үшін


BASE_DIR = Path(__file__).resolve().parent  # Ағымдағы файлдың негізгі қалтасын анықтау
load_dotenv(BASE_DIR / ".env")  # .env файлын жүктеп, орта айнымалыларына қосу


def _get_bool(name: str, default: bool) -> bool:
    # Орта айнымалысынан bool мәнін оқу
    value = os.getenv(name)  # Айнымалы мәнін алу
    if value is None:  # Егер айнымалы орнатылмаған болса
        return default  # Әдепкі мәнді қайтару
    return value.strip().lower() in {"1", "true", "yes", "on"}  # Мәнді bool-ға түрлендіру


def _get_int(name: str, default: int) -> int:
    # Орта айнымалысынан int мәнін оқу
    raw_value = os.getenv(name, "").strip()  # Айнымалы мәнін алып, бос орындарды тазалау
    if not raw_value:  # Егер мән бос болса
        return default  # Әдепкі мәнді қайтару
    try:
        return int(raw_value)  # Мәнді int-ке түрлендіру
    except ValueError:  # Егер түрлендіру мүмкін болмаса
        return default  # Әдепкі мәнді қайтару


def _detect_webhook_url() -> str:
    # Webhook URL-ді орта айнымалыларынан автоматты анықтау
    for env_name in ("WEBHOOK_URL", "RENDER_EXTERNAL_URL", "RAILWAY_PUBLIC_DOMAIN"):  # Мүмкін айнымалы атаулары
        value = os.getenv(env_name, "").strip()  # Айнымалы мәнін алу
        if not value:  # Егер мән бос болса
            continue  # Келесі айнымалыға өту
        if value.startswith("http://") or value.startswith("https://"):  # Егер URL дайын болса
            return value.rstrip("/")  # Соңғы слешті алып қайтару
        return "https://{0}".format(value.rstrip("/"))  # https:// қосып қайтару
    return ""  # Ешбір айнымалы табылмаса бос жол қайтару


# Telegram бот токені — BotFather-дан алынады
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Google Gemini API кілті
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Қолданылатын Gemini модель атауы
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"

# OpenRouter API кілті
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

# Қолданылатын OpenRouter модель атауы
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini").strip() or "openai/gpt-4.1-mini"

# OpenRouter API мекенжайы
OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions").strip() or "https://openrouter.ai/api/v1/chat/completions"

# Әдепкі AI провайдері (google немесе openrouter)
DEFAULT_AI_PROVIDER = os.getenv("DEFAULT_AI_PROVIDER", "google").strip().lower() or "google"

# Webhook толық URL мекенжайы
WEBHOOK_URL = _detect_webhook_url()

# Webhook сұрауларды қабылдайтын жол
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/telegram").strip() or "/telegram"

# Сервер тыңдайтын IP мекенжайы (0.0.0.0 — барлық интерфейс)
WEBHOOK_LISTEN = os.getenv("WEBHOOK_LISTEN", "0.0.0.0").strip() or "0.0.0.0"

# Сервер порты (PORT немесе WEBHOOK_PORT айнымалысынан, әдепкі 8080)
WEBHOOK_PORT = _get_int("PORT", _get_int("WEBHOOK_PORT", 8080))

# HeadHunter API негізгі мекенжайы
HH_API_BASE_URL = os.getenv("HH_API_BASE_URL", "https://api.hh.ru").strip() or "https://api.hh.ru"

# Bing іздеу URL мекенжайы
BING_SEARCH_URL = os.getenv("BING_SEARCH_URL", "https://www.bing.com/search").strip() or "https://www.bing.com/search"

# Әдепкі ел аймағының ID-і (40 — Қазақстан)
DEFAULT_COUNTRY_AREA_ID = os.getenv("DEFAULT_COUNTRY_AREA_ID", "40").strip() or "40"

# HTTP сұраныс уақыт шегі (секунд)
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "20").strip() or "20")

# Жұмыс нәтижелерінің максимал саны (3-тен 5-ке дейін)
JOB_RESULTS_LIMIT = max(3, min(_get_int("JOB_RESULTS_LIMIT", 5), 5))

# Веб іздеу нәтижелерінің максимал саны (1-ден 5-ке дейін)
PUBLIC_SEARCH_RESULTS_LIMIT = max(1, min(_get_int("PUBLIC_SEARCH_RESULTS_LIMIT", 3), 5))

# Ашық веб іздеуді қосу/өшіру
ENABLE_PUBLIC_WEB_SEARCH = _get_bool("ENABLE_PUBLIC_WEB_SEARCH", True)

# AI ассистентін қосу/өшіру
ENABLE_AI_ASSISTANT = _get_bool("ENABLE_AI_ASSISTANT", True)

# AI жауабының максимал токен саны (200-ден 1000-ға дейін)
AI_MAX_OUTPUT_TOKENS = max(200, min(_get_int("AI_MAX_OUTPUT_TOKENS", 500), 1000))


def configure_logging() -> None:
    # Лог жүйесін баптау
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),  # Лог деңгейі (INFO, DEBUG, ERROR т.б.)
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",  # Лог форматы: уақыт, деңгей, модуль, хабарлама
    )