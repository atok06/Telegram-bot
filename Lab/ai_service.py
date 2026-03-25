from __future__ import annotations
from typing import Any, Dict

import httpx

from config import (
    AI_MAX_OUTPUT_TOKENS,
    DEFAULT_AI_PROVIDER,
    ENABLE_AI_ASSISTANT,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_API_URL,
    OPENROUTER_MODEL,
    REQUEST_TIMEOUT_SECONDS,
)


SUPPORTED_AI_PROVIDERS = {"google", "openrouter"}

CAREER_SYSTEM_PROMPT = (
    "You are a Telegram career assistant for job seekers in Kazakhstan and CIS markets. "
    "Reply in simple Kazakh or the user's language. Keep answers short, practical, and specific. "
    "Do not invent current vacancies, salaries, or company facts unless they were supplied in the prompt. "
    "If vacancy details, client details, or recruiter details look fake, contradictory, or unsafe, "
    "reply with a short error message instead of normal advice. "
    "If profile details are missing, say what is missing in one short sentence. "
    "For resume, interview, and skills advice, give actionable steps. "
    "Avoid fluff, unsafe advice, and long introductions."
)


def normalize_provider(provider: str | None) -> str:
    value = (provider or DEFAULT_AI_PROVIDER or "google").strip().lower()
    if value not in SUPPORTED_AI_PROVIDERS:
        return "google"
    return value


def ai_provider_configured(provider: str | None = None) -> bool:
    if not ENABLE_AI_ASSISTANT:
        return False

    normalized = normalize_provider(provider)
    if normalized == "google":
        return bool(GEMINI_API_KEY)
    return bool(OPENROUTER_API_KEY)


def any_ai_available() -> bool:
    return ai_provider_configured("google") or ai_provider_configured("openrouter")


def build_profile_context(profile: Dict[str, object]) -> str:
    if not profile:
        return "User profile is empty."

    parts = [
        "City: {0}".format(profile.get("city") or "not set"),
        "Field: {0}".format(profile.get("field") or "not set"),
        "Experience: {0}".format(profile.get("experience") or "not set"),
        "Work mode: {0}".format(profile.get("work_mode") or "not set"),
        "Salary: {0}".format(profile.get("salary_text") or "not set"),
    ]
    return "\n".join(parts)


async def ask_career_ai(
    *,
    prompt: str,
    profile: Dict[str, object] | None = None,
    provider: str | None = None,
) -> str:
    normalized = _resolve_provider(provider)
    if not normalized:
        raise RuntimeError("AI provider is not configured.")

    final_prompt = (
        "User profile:\n{0}\n\n"
        "Task:\n{1}"
    ).format(build_profile_context(profile or {}), prompt.strip())

    if normalized == "google":
        return await _ask_gemini(final_prompt)
    return await _ask_openrouter(final_prompt)


def _resolve_provider(provider: str | None) -> str:
    normalized = normalize_provider(provider)
    if ai_provider_configured(normalized):
        return normalized
    if ai_provider_configured("google"):
        return "google"
    if ai_provider_configured("openrouter"):
        return "openrouter"
    return ""


async def _ask_gemini(prompt: str) -> str:
    payload = {
        "system_instruction": {"parts": [{"text": CAREER_SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.5,
            "maxOutputTokens": AI_MAX_OUTPUT_TOKENS,
        },
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(_gemini_url(), json=payload)
        response.raise_for_status()
        data = response.json()

    candidates = data.get("candidates") or []
    for candidate in candidates:
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        texts = [part.get("text", "").strip() for part in parts if isinstance(part, dict)]
        answer = "\n".join(text for text in texts if text).strip()
        if answer:
            return answer
    raise RuntimeError("Gemini returned an empty answer.")


async def _ask_openrouter(prompt: str) -> str:
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": CAREER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.5,
        "max_tokens": AI_MAX_OUTPUT_TOKENS,
    }
    headers = {
        "Authorization": "Bearer {0}".format(OPENROUTER_API_KEY),
        "Content-Type": "application/json",
        "X-OpenRouter-Title": "Job Assistant Bot",
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(OPENROUTER_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenRouter returned no choices.")

    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(item["text"].strip())
        answer = "\n".join(text for text in texts if text).strip()
        if answer:
            return answer
    raise RuntimeError("OpenRouter returned an empty answer.")


def _gemini_url() -> str:
    return "https://generativelanguage.googleapis.com/v1beta/models/{0}:generateContent?key={1}".format(
        GEMINI_MODEL,
        GEMINI_API_KEY,
    )
