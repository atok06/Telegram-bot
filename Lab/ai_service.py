from __future__ import annotations  # Python 3.10+ type hint синтаксисін ескі версияларда қолдану үшін
from typing import Any, Dict  # Тип аннотациялары үшін

import httpx  # Async HTTP сұраныстар жіберу кітапханасы

# Конфиг файлынан барлық керекті параметрлерді импорттау
from config import (
    AI_MAX_OUTPUT_TOKENS,      # AI жауабының максимал токен саны
    DEFAULT_AI_PROVIDER,       # Әдепкі AI провайдері (google немесе openrouter)
    ENABLE_AI_ASSISTANT,       # AI қосулы/өшірулі екенін білдіретін флаг
    GEMINI_API_KEY,            # Google Gemini API кілті
    GEMINI_MODEL,              # Қолданылатын Gemini модель атауы
    OPENROUTER_API_KEY,        # OpenRouter API кілті
    OPENROUTER_API_URL,        # OpenRouter API мекенжайы
    OPENROUTER_MODEL,          # Қолданылатын OpenRouter модель атауы
    REQUEST_TIMEOUT_SECONDS,   # HTTP сұраныс уақыт шегі (секунд)
)


# Қолдау көрсетілетін AI провайдерлер тізімі
SUPPORTED_AI_PROVIDERS = {"google", "openrouter"}

# AI карьера ассистентінің жүйелік нұсқауы (system prompt)
CAREER_SYSTEM_PROMPT = (
    "You are a Telegram career assistant for job seekers in Kazakhstan and CIS markets. "  # Рөлді анықтау
    "Reply in simple Kazakh or the user's language. Keep answers short, practical, and specific. "  # Жауап форматы
    "Do not invent current vacancies, salaries, or company facts unless they were supplied in the prompt. "  # Жалған мәлімет бермеу
    "If vacancy details, client details, or recruiter details look fake, contradictory, or unsafe, "  # Қауіпті деректер анықтау
    "reply with a short error message instead of normal advice. "  # Қате хабарлама жіберу
    "If profile details are missing, say what is missing in one short sentence. "  # Жетіспейтін деректерді хабарлау
    "For resume, interview, and skills advice, give actionable steps. "  # Нақты кеңес беру
    "Avoid fluff, unsafe advice, and long introductions."  # Артық сөзден аулақ болу
)


def normalize_provider(provider: str | None) -> str:
    # Провайдер атауын стандартты пішінге келтіру
    value = (provider or DEFAULT_AI_PROVIDER or "google").strip().lower()  # Бос орындарды алып тастап, кіші әріпке түрлендіру
    if value not in SUPPORTED_AI_PROVIDERS:  # Егер провайдер тізімде жоқ болса
        return "google"  # Әдепкі Google-ді қайтару
    return value  # Дұрыс провайдерді қайтару


def ai_provider_configured(provider: str | None = None) -> bool:
    # Берілген провайдердің конфигурацияланғанын тексеру
    if not ENABLE_AI_ASSISTANT:  # Егер AI өшірулі болса
        return False  # False қайтару

    normalized = normalize_provider(provider)  # Провайдер атауын нормализациялау
    if normalized == "google":  # Егер Google провайдері болса
        return bool(GEMINI_API_KEY)  # Gemini API кілті бар-жоғын тексеру
    return bool(OPENROUTER_API_KEY)  # OpenRouter API кілті бар-жоғын тексеру


def any_ai_available() -> bool:
    # Кем дегенде бір AI провайдері қолжетімді екенін тексеру
    return ai_provider_configured("google") or ai_provider_configured("openrouter")  # Google немесе OpenRouter дайын ба


def build_profile_context(profile: Dict[str, object]) -> str:
    # Пайдаланушы профилінен мәтіндік контекст жасау
    if not profile:  # Егер профиль бос болса
        return "User profile is empty."  # Бос профиль туралы хабар қайтару

    parts = [  # Профиль өрістерін тізім ретінде жинау
        "City: {0}".format(profile.get("city") or "not set"),          # Қала
        "Field: {0}".format(profile.get("field") or "not set"),        # Сала
        "Experience: {0}".format(profile.get("experience") or "not set"),  # Тәжірибе
        "Work mode: {0}".format(profile.get("work_mode") or "not set"),    # Жұмыс форматы
        "Salary: {0}".format(profile.get("salary_text") or "not set"),    # Жалақы
    ]
    return "\n".join(parts)  # Барлық өрістерді жаңа жолмен біріктіріп қайтару


async def ask_career_ai(
    *,
    prompt: str,                          # Пайдаланушының сұрақ мәтіні
    profile: Dict[str, object] | None = None,  # Пайдаланушы профилі (міндетті емес)
    provider: str | None = None,          # AI провайдері (міндетті емес)
) -> str:
    # AI-ға карьера сұрағын жіберетін негізгі функция
    normalized = _resolve_provider(provider)  # Қолжетімді провайдерді анықтау
    if not normalized:  # Егер провайдер табылмаса
        raise RuntimeError("AI provider is not configured.")  # Қате шығару

    # Профиль мен сұрақты біріктіріп толық prompt жасау
    final_prompt = (
        "User profile:\n{0}\n\n"
        "Task:\n{1}"
    ).format(build_profile_context(profile or {}), prompt.strip())

    if normalized == "google":  # Егер Google провайдері болса
        return await _ask_gemini(final_prompt)  # Gemini-ге сұрау жіберу
    return await _ask_openrouter(final_prompt)  # OpenRouter-ге сұрау жіберу


def _resolve_provider(provider: str | None) -> str:
    # Қолжетімді провайдерді автоматты анықтау
    normalized = normalize_provider(provider)  # Провайдер атауын нормализациялау
    if ai_provider_configured(normalized):  # Егер сұралған провайдер дайын болса
        return normalized  # Сол провайдерді қайтару
    if ai_provider_configured("google"):  # Егер Google қолжетімді болса
        return "google"  # Google-ді қайтару
    if ai_provider_configured("openrouter"):  # Егер OpenRouter қолжетімді болса
        return "openrouter"  # OpenRouter-ді қайтару
    return ""  # Ешбір провайдер жоқ — бос жол қайтару


async def _ask_gemini(prompt: str) -> str:
    # Google Gemini API-ге сұрау жіберу
    payload = {
        "system_instruction": {"parts": [{"text": CAREER_SYSTEM_PROMPT}]},  # Жүйелік нұсқау
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],        # Пайдаланушы хабарламасы
        "generationConfig": {
            "temperature": 0.5,                    # Жауап кездейсоқтығы (0=тұрақты, 1=шығармашыл)
            "maxOutputTokens": AI_MAX_OUTPUT_TOKENS,  # Максимал жауап ұзындығы
        },
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:  # HTTP клиент ашу
        response = await client.post(_gemini_url(), json=payload)  # POST сұрауы жіберу
        response.raise_for_status()  # Қате статус кодында exception шығару
        data = response.json()  # JSON жауабын өңдеу

    candidates = data.get("candidates") or []  # Жауап нұсқаларын алу
    for candidate in candidates:  # Әр нұсқаны тексеру
        content = candidate.get("content") or {}  # Мазмұнды алу
        parts = content.get("parts") or []  # Бөліктерді алу
        texts = [part.get("text", "").strip() for part in parts if isinstance(part, dict)]  # Мәтіндерді жинау
        answer = "\n".join(text for text in texts if text).strip()  # Мәтіндерді біріктіру
        if answer:  # Егер жауап бос болмаса
            return answer  # Жауапты қайтару
    raise RuntimeError("Gemini returned an empty answer.")  # Бос жауап — қате шығару


async def _ask_openrouter(prompt: str) -> str:
    # OpenRouter API-ге сұрау жіберу
    payload = {
        "model": OPENROUTER_MODEL,  # Қолданылатын модель
        "messages": [
            {"role": "system", "content": CAREER_SYSTEM_PROMPT},  # Жүйелік нұсқау
            {"role": "user", "content": prompt},                   # Пайдаланушы хабарламасы
        ],
        "temperature": 0.5,                     # Жауап кездейсоқтығы
        "max_tokens": AI_MAX_OUTPUT_TOKENS,      # Максимал токен саны
    }
    headers = {
        "Authorization": "Bearer {0}".format(OPENROUTER_API_KEY),  # API кілті арқылы аутентификация
        "Content-Type": "application/json",                         # JSON форматы
        "X-OpenRouter-Title": "Job Assistant Bot",                  # Қосымша атауы
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:  # HTTP клиент ашу
        response = await client.post(OPENROUTER_API_URL, headers=headers, json=payload)  # POST сұрауы
        response.raise_for_status()  # Қате статус кодында exception шығару
        data = response.json()  # JSON жауабын өңдеу

    choices = data.get("choices") or []  # Жауап нұсқаларын алу
    if not choices:  # Егер нұсқалар жоқ болса
        raise RuntimeError("OpenRouter returned no choices.")  # Қате шығару

    message = choices[0].get("message") or {}  # Бірінші нұсқаның хабарламасын алу
    content = message.get("content", "")  # Мазмұнды алу
    if isinstance(content, str) and content.strip():  # Егер мазмұн мәтін болса
        return content.strip()  # Тазаланған мәтінді қайтару
    if isinstance(content, list):  # Егер мазмұн тізім болса
        texts = []  # Мәтіндер тізімі
        for item in content:  # Әр элементті тексеру
            if isinstance(item, dict) and isinstance(item.get("text"), str):  # Мәтін бар-жоғын тексеру
                texts.append(item["text"].strip())  # Мәтінді тізімге қосу
        answer = "\n".join(text for text in texts if text).strip()  # Мәтіндерді біріктіру
        if answer:  # Егер жауап бос болмаса
            return answer  # Жауапты қайтару
    raise RuntimeError("OpenRouter returned an empty answer.")  # Бос жауап — қате шығару


def _gemini_url() -> str:
    # Gemini API URL мекенжайын жасау
    return "https://generativelanguage.googleapis.com/v1beta/models/{0}:generateContent?key={1}".format(
        GEMINI_MODEL,   # Модель атауы URL-ге кірістіру
        GEMINI_API_KEY, # API кілтін URL-ге кірістіру
    )