from telegram import Update

import request_database


def save_log_event(
    *,
    direction: str,
    event_type: str,
    content: str = "",
    update: Update | None = None,
    message=None,
    metadata: dict | None = None,
) -> None:
    source_message = message or (update.effective_message if update else None)
    user = source_message.from_user if source_message else (update.effective_user if update else None)
    chat = source_message.chat if source_message else (update.effective_chat if update else None)
    full_name = " ".join(
        part for part in [getattr(user, "first_name", "") or "", getattr(user, "last_name", "") or ""] if part
    ).strip()

    request_database.log_event(
        direction=direction,
        event_type=event_type,
        user_id=str(getattr(user, "id", "") or ""),
        chat_id=str(getattr(chat, "id", "") or ""),
        username=getattr(user, "username", "") or "",
        full_name=full_name,
        content=content,
        metadata=metadata,
    )


def log_system_event(event_type: str, content: str, metadata: dict | None = None) -> None:
    request_database.log_event(
        direction="system",
        event_type=event_type,
        content=content,
        metadata=metadata,
    )
