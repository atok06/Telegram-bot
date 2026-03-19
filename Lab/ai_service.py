import logging

import httpx

from config import AI_SYSTEM_PROMPT, OPENROUTER_API_KEY, OPENROUTER_API_URL, OPENROUTER_MODEL
from request_logger import save_log_event


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


async def ask_openrouter(prompt: str, user_id: str) -> str:
    """Send one prompt to OpenRouter and return the assistant text."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not configured.")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-OpenRouter-Title": "Telegram AI Bot",
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
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

    return answer


async def send_ai_reply(
    message,
    prompt: str,
    user_id: str,
    source_event: str = "ai_request",
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
        answer = await ask_openrouter(prompt=prompt, user_id=user_id)
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
    save_log_event(
        direction="bot",
        event_type="ai_response",
        content=answer,
        message=message,
        metadata={"source_event": source_event, "prompt": prompt},
    )
    return answer
