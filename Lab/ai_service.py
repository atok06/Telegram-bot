import base64
import logging
import mimetypes
from pathlib import Path

import httpx

from config import (
    AI_MEMORY_MESSAGES,
    AI_SYSTEM_PROMPT,
    DEFAULT_AI_PROVIDER,
    ENABLE_WEB_SEARCH,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_API_URL,
    OPENROUTER_MODEL,
    OPENROUTER_VISION_MODEL,
)
from request_database import fetch_recent_conversation
from request_logger import save_log_event
from web_search import WebSearchResult, format_web_context, search_web, should_use_web_search


logger = logging.getLogger(__name__)

SUPPORTED_AI_PROVIDERS = ("google", "openrouter")
PROVIDER_LABELS = {
    "google": "Google Gemini",
    "openrouter": "OpenRouter",
}


def normalize_provider(provider: str | None) -> str:
    normalized = (provider or DEFAULT_AI_PROVIDER).strip().lower()
    if normalized not in SUPPORTED_AI_PROVIDERS:
        return DEFAULT_AI_PROVIDER
    return normalized


def get_provider_label(provider: str | None) -> str:
    return PROVIDER_LABELS[normalize_provider(provider)]


def extract_ai_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()

    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue

        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
            continue

        nested_text = item.get("content")
        if isinstance(nested_text, str):
            parts.append(nested_text)

    return "\n".join(part.strip() for part in parts if part).strip()


def extract_openrouter_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip()

    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return message.strip()

    if isinstance(error, str):
        return error.strip()

    message = payload.get("message")
    if isinstance(message, str):
        return message.strip()

    return response.text.strip()


def extract_gemini_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip()

    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return message.strip()

    return response.text.strip()


def _provider_not_configured_message(provider: str) -> str:
    if provider == "google":
        return "GEMINI_API_KEY configured емес."
    return "OPENROUTER_API_KEY configured емес."


def _history_event_to_message(event: dict[str, str]) -> dict[str, str] | None:
    content = event.get("content", "").strip()
    if not content:
        return None

    event_type = event.get("event_type", "")
    if event_type in {"ai_response", "image_objects"}:
        return {"role": "assistant", "content": content}
    if event_type == "audio_transcript":
        return {"role": "user", "content": f"[voice transcript] {content}"}
    return {"role": "user", "content": content}


def _format_history_for_prompt(history: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for event in history:
        message = _history_event_to_message(event)
        if message is None:
            continue
        role = "Assistant" if message["role"] == "assistant" else "User"
        lines.append(f"{role}: {message['content']}")
    return "\n".join(lines)


def _serialize_web_results(results: list[WebSearchResult]) -> list[dict[str, str]]:
    return [{"title": item.title, "url": item.url} for item in results]


async def _collect_request_context(
    *,
    prompt: str,
    user_id: str,
    chat_id: str,
    current_event_id: int | None,
    force_web_search: bool,
) -> tuple[list[dict[str, str]], list[WebSearchResult], int]:
    history: list[dict[str, str]] = []
    if AI_MEMORY_MESSAGES > 0:
        history = fetch_recent_conversation(
            user_id=user_id,
            chat_id=chat_id,
            limit=AI_MEMORY_MESSAGES,
            before_id=current_event_id,
        )

    web_results: list[WebSearchResult] = []
    if ENABLE_WEB_SEARCH and should_use_web_search(prompt, force_web_search):
        try:
            web_results = await search_web(prompt)
        except Exception as exc:
            logger.warning("Web search failed for %r: %s", prompt, exc)

    return history, web_results, len(history)


def _build_openrouter_messages(
    *,
    prompt: str,
    history: list[dict[str, str]],
    web_results: list[WebSearchResult],
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": AI_SYSTEM_PROMPT}]
    for event in history:
        message = _history_event_to_message(event)
        if message is not None:
            messages.append(message)

    web_context = format_web_context(web_results)
    if web_context:
        messages.append(
            {
                "role": "system",
                "content": (
                    "Web search snippets from public internet sources are provided below. "
                    "Prefer them for current facts, and mention when the available snippets are incomplete.\n\n"
                    f"{web_context}"
                ),
            }
        )

    messages.append({"role": "user", "content": prompt})
    return messages


def _build_gemini_prompt(
    *,
    prompt: str,
    history: list[dict[str, str]],
    web_results: list[WebSearchResult],
) -> str:
    sections: list[str] = []
    history_text = _format_history_for_prompt(history)
    if history_text:
        sections.append(f"Conversation history:\n{history_text}")

    web_context = format_web_context(web_results)
    if web_context:
        sections.append(f"Web search snippets:\n{web_context}")

    sections.append(f"User request:\n{prompt}")
    return "\n\n".join(sections)


def _openrouter_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-OpenRouter-Title": "Telegram AI Bot",
    }


def _extract_openrouter_answer(data: dict) -> str:
    choices = data.get("choices", [])
    if not choices:
        raise ValueError("OpenRouter returned no choices.")

    message = choices[0].get("message", {})
    answer = extract_ai_text(message.get("content", ""))
    if not answer:
        raise ValueError("OpenRouter returned an empty answer.")
    return answer


def _gemini_api_url(model: str, api_key: str) -> str:
    return (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={api_key}"
    )


def _extract_gemini_answer(data: dict) -> str:
    candidates = data.get("candidates", [])
    for candidate in candidates:
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        texts = [part.get("text", "").strip() for part in parts if isinstance(part, dict)]
        answer = "\n".join(text for text in texts if text).strip()
        if answer:
            return answer
    raise ValueError("Gemini returned an empty answer.")


def _build_image_data_url(file_path: str) -> str:
    path = Path(file_path)
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _build_gemini_image_part(file_path: str) -> dict[str, dict[str, str]]:
    path = Path(file_path)
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "inline_data": {
            "mime_type": mime_type,
            "data": encoded,
        }
    }


async def _ask_gemini(
    *,
    prompt: str,
    history: list[dict[str, str]],
    web_results: list[WebSearchResult],
) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError(_provider_not_configured_message("google"))

    payload = {
        "system_instruction": {"parts": [{"text": AI_SYSTEM_PROMPT}]},
        "contents": [
            {
                "role": "user",
                "parts": [{"text": _build_gemini_prompt(prompt=prompt, history=history, web_results=web_results)}],
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 400,
        },
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(_gemini_api_url(GEMINI_MODEL, GEMINI_API_KEY), json=payload)
        response.raise_for_status()
        data = response.json()
    return _extract_gemini_answer(data)


async def _ask_openrouter(
    *,
    prompt: str,
    user_id: str,
    history: list[dict[str, str]],
    web_results: list[WebSearchResult],
) -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError(_provider_not_configured_message("openrouter"))

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": _build_openrouter_messages(prompt=prompt, history=history, web_results=web_results),
        "temperature": 0.7,
        "max_completion_tokens": 400,
        "user": user_id,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(OPENROUTER_API_URL, headers=_openrouter_headers(), json=payload)
        response.raise_for_status()
        data = response.json()
    return _extract_openrouter_answer(data)


async def ask_ai(
    *,
    prompt: str,
    user_id: str,
    provider: str,
    chat_id: str = "",
    current_event_id: int | None = None,
    force_web_search: bool = False,
) -> tuple[str, list[WebSearchResult], int]:
    provider = normalize_provider(provider)
    history, web_results, history_count = await _collect_request_context(
        prompt=prompt,
        user_id=user_id,
        chat_id=chat_id,
        current_event_id=current_event_id,
        force_web_search=force_web_search,
    )
    if provider == "google":
        answer = await _ask_gemini(prompt=prompt, history=history, web_results=web_results)
    else:
        answer = await _ask_openrouter(
            prompt=prompt,
            user_id=user_id,
            history=history,
            web_results=web_results,
        )

    return answer, web_results, history_count


async def _analyze_image_with_gemini(file_path: str, prompt: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError(_provider_not_configured_message("google"))

    image_prompt = (
        prompt.strip()
        or "Analyze this image and list the main visible objects. "
        "Reply in Kazakh with the heading 'Танылған объектілер:' and a short bullet list."
    )
    payload = {
        "system_instruction": {
            "parts": [
                {
                    "text": (
                        "You identify visible objects in images for a Telegram bot. "
                        "Mention only objects that are clearly visible and stay concise."
                    )
                }
            ]
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": image_prompt},
                    _build_gemini_image_part(file_path),
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 250,
        },
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(_gemini_api_url(GEMINI_MODEL, GEMINI_API_KEY), json=payload)
        response.raise_for_status()
        data = response.json()
    return _extract_gemini_answer(data)


async def _analyze_image_with_openrouter(file_path: str, user_id: str, prompt: str) -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError(_provider_not_configured_message("openrouter"))

    image_prompt = (
        prompt.strip()
        or "Analyze this image and list the main visible objects only. "
        "Reply in Kazakh with the heading 'Танылған объектілер:' and a short bullet list. "
        "If something is uncertain, mark it briefly."
    )
    payload = {
        "model": OPENROUTER_VISION_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You identify visible objects in images for a Telegram bot. "
                    "Be concise and mention only objects that are actually visible."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": image_prompt},
                    {"type": "image_url", "image_url": {"url": _build_image_data_url(file_path), "detail": "auto"}},
                ],
            },
        ],
        "temperature": 0.2,
        "max_completion_tokens": 250,
        "user": user_id,
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(OPENROUTER_API_URL, headers=_openrouter_headers(), json=payload)
        response.raise_for_status()
        data = response.json()
    return _extract_openrouter_answer(data)


async def analyze_image_objects(
    file_path: str,
    user_id: str,
    provider: str,
    prompt: str = "",
) -> str:
    provider = normalize_provider(provider)
    if provider == "google":
        return await _analyze_image_with_gemini(file_path, prompt)
    return await _analyze_image_with_openrouter(file_path, user_id, prompt)


async def send_ai_reply(
    message,
    prompt: str,
    user_id: str,
    source_event: str = "ai_request",
    *,
    provider: str | None = None,
    chat_id: str = "",
    current_event_id: int | None = None,
    force_web_search: bool = False,
) -> str | None:
    provider = normalize_provider(provider)
    if provider == "google" and not GEMINI_API_KEY:
        response_text = "Gemini API кілті қойылмаған. Lab/.env немесе Render env ішіне GEMINI_API_KEY енгізіңіз."
        await message.reply_text(response_text)
        save_log_event(
            direction="bot",
            event_type="ai_response_error",
            content=response_text,
            message=message,
            metadata={"source_event": source_event, "provider": provider},
        )
        return None

    if provider == "openrouter" and not OPENROUTER_API_KEY:
        response_text = "OpenRouter API кілті қойылмаған. Lab/.env немесе Render env ішіне OPENROUTER_API_KEY енгізіңіз."
        await message.reply_text(response_text)
        save_log_event(
            direction="bot",
            event_type="ai_response_error",
            content=response_text,
            message=message,
            metadata={"source_event": source_event, "provider": provider},
        )
        return None

    try:
        answer, web_results, history_count = await ask_ai(
            prompt=prompt,
            user_id=user_id,
            provider=provider,
            chat_id=chat_id,
            current_event_id=current_event_id,
            force_web_search=force_web_search,
        )
    except httpx.HTTPStatusError as exc:
        if provider == "google":
            error_message = extract_gemini_error(exc.response) or "Unknown Gemini error."
            response_text = f"Gemini қатесі ({exc.response.status_code}): {error_message}"
        else:
            error_message = extract_openrouter_error(exc.response) or "Unknown OpenRouter error."
            response_text = f"OpenRouter қатесі ({exc.response.status_code}): {error_message}"

        logger.error("%s HTTP %s error: %s", get_provider_label(provider), exc.response.status_code, error_message)
        await message.reply_text(response_text)
        save_log_event(
            direction="bot",
            event_type="ai_response_error",
            content=response_text,
            message=message,
            metadata={
                "source_event": source_event,
                "provider": provider,
                "status_code": exc.response.status_code,
                "http_error": error_message,
            },
        )
        return None
    except Exception as exc:
        logger.error("%s request failed: %s", get_provider_label(provider), exc)
        response_text = f"{get_provider_label(provider)} арқылы жауап алу кезінде қате шықты."
        await message.reply_text(response_text)
        save_log_event(
            direction="bot",
            event_type="ai_response_error",
            content=response_text,
            message=message,
            metadata={"source_event": source_event, "provider": provider, "error": str(exc)},
        )
        return None

    await message.reply_text(answer)
    metadata: dict[str, object] = {
        "source_event": source_event,
        "provider": provider,
        "prompt": prompt,
        "history_messages": history_count,
    }
    if web_results:
        metadata["web_results"] = _serialize_web_results(web_results)

    save_log_event(
        direction="bot",
        event_type="ai_response",
        content=answer,
        message=message,
        metadata=metadata,
    )
    return answer
