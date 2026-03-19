import logging

import httpx

from config import (
    AI_MEMORY_MESSAGES,
    AI_SYSTEM_PROMPT,
    ENABLE_WEB_SEARCH,
    OPENROUTER_API_KEY,
    OPENROUTER_API_URL,
    OPENROUTER_MODEL,
)
from request_database import fetch_recent_conversation
from request_logger import save_log_event
from web_search import WebSearchResult, format_web_context, search_web, should_use_web_search


logger = logging.getLogger(__name__)


def extract_ai_text(content: object) -> str:
    """Normalize text from OpenRouter chat responses."""
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
    """Pull a readable error message from an OpenRouter error response."""
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


def _history_event_to_message(event: dict[str, str]) -> dict[str, str] | None:
    content = event.get("content", "").strip()
    if not content:
        return None

    event_type = event.get("event_type", "")
    if event_type == "ai_response":
        return {"role": "assistant", "content": content}
    if event_type == "audio_transcript":
        return {"role": "user", "content": f"[voice transcript] {content}"}
    return {"role": "user", "content": content}


def _serialize_web_results(results: list[WebSearchResult]) -> list[dict[str, str]]:
    return [{"title": item.title, "url": item.url} for item in results]


async def build_openrouter_messages(
    *,
    prompt: str,
    user_id: str,
    chat_id: str = "",
    current_event_id: int | None = None,
    force_web_search: bool = False,
) -> tuple[list[dict[str, str]], list[WebSearchResult], int]:
    messages: list[dict[str, str]] = [{"role": "system", "content": AI_SYSTEM_PROMPT}]
    history_count = 0

    if AI_MEMORY_MESSAGES > 0:
        history = fetch_recent_conversation(
            user_id=user_id,
            chat_id=chat_id,
            limit=AI_MEMORY_MESSAGES,
            before_id=current_event_id,
        )
        for event in history:
            message = _history_event_to_message(event)
            if message is None:
                continue
            messages.append(message)
            history_count += 1

    web_results: list[WebSearchResult] = []
    if ENABLE_WEB_SEARCH and should_use_web_search(prompt, force_web_search):
        try:
            web_results = await search_web(prompt)
        except Exception as exc:
            logger.warning("Web search failed for %r: %s", prompt, exc)
        else:
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
    return messages, web_results, history_count


async def ask_openrouter(
    prompt: str,
    user_id: str,
    chat_id: str = "",
    current_event_id: int | None = None,
    force_web_search: bool = False,
) -> tuple[str, list[WebSearchResult], int]:
    """Send one prompt to OpenRouter and return the assistant text."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not configured.")

    messages, web_results, history_count = await build_openrouter_messages(
        prompt=prompt,
        user_id=user_id,
        chat_id=chat_id,
        current_event_id=current_event_id,
        force_web_search=force_web_search,
    )
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-OpenRouter-Title": "Telegram AI Bot",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_completion_tokens": 400,
        "user": user_id,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(OPENROUTER_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    choices = data.get("choices", [])
    if not choices:
        raise ValueError("OpenRouter returned no choices.")

    message = choices[0].get("message", {})
    answer = extract_ai_text(message.get("content", ""))
    if not answer:
        raise ValueError("OpenRouter returned an empty answer.")

    return answer, web_results, history_count


async def send_ai_reply(
    message,
    prompt: str,
    user_id: str,
    source_event: str = "ai_request",
    *,
    chat_id: str = "",
    current_event_id: int | None = None,
    force_web_search: bool = False,
) -> str | None:
    """Request an AI answer and send it back to Telegram."""
    if not OPENROUTER_API_KEY:
        response_text = (
            "OpenRouter токені қойылмаған. "
            "Lab/.env файлына OPENROUTER_API_KEY мәнін жазыңыз."
        )
        await message.reply_text(response_text)
        save_log_event(
            direction="bot",
            event_type="ai_response_error",
            content=response_text,
            message=message,
            metadata={"source_event": source_event},
        )
        return None

    try:
        answer, web_results, history_count = await ask_openrouter(
            prompt=prompt,
            user_id=user_id,
            chat_id=chat_id,
            current_event_id=current_event_id,
            force_web_search=force_web_search,
        )
    except httpx.HTTPStatusError as exc:
        error_message = extract_openrouter_error(exc.response) or "Unknown OpenRouter error."
        logger.error("OpenRouter HTTP %s error: %s", exc.response.status_code, error_message)
        response_text = f"OpenRouter қатесі ({exc.response.status_code}): {error_message}"
        await message.reply_text(response_text)
        save_log_event(
            direction="bot",
            event_type="ai_response_error",
            content=response_text,
            message=message,
            metadata={
                "source_event": source_event,
                "status_code": exc.response.status_code,
                "http_error": error_message,
            },
        )
        return None
    except Exception as exc:
        logger.error("OpenRouter request failed: %s", exc)
        response_text = "AI жауап алу кезінде қате шықты."
        await message.reply_text(response_text)
        save_log_event(
            direction="bot",
            event_type="ai_response_error",
            content=response_text,
            message=message,
            metadata={"source_event": source_event, "error": str(exc)},
        )
        return None

    await message.reply_text(answer)
    metadata: dict[str, object] = {
        "source_event": source_event,
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
