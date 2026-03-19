"""Telegram update handlers and application wiring."""

import logging
from pathlib import Path

import audio_recognition
from ai_service import send_ai_reply
from config import BASE_DIR
from request_logger import log_system_event, save_log_event
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from tts_service import DEFAULT_TTS_LANGUAGE, generate_speech


logger = logging.getLogger(__name__)


def remember_last_text(context: ContextTypes.DEFAULT_TYPE, key: str, text: str) -> None:
    context.user_data[key] = text
    context.user_data["last_result_text"] = text


def resolve_text_for_speech(context: ContextTypes.DEFAULT_TYPE, explicit_text: str) -> str:
    if explicit_text.strip():
        return explicit_text.strip()

    for key in ("last_result_text", "last_audio_text"):
        stored_text = context.user_data.get(key, "")
        if isinstance(stored_text, str) and stored_text.strip():
            return stored_text.strip()

    return ""


def get_user_speech_language(context: ContextTypes.DEFAULT_TYPE) -> str:
    saved_language = context.user_data.get("speech_recognition_lang", "")
    if isinstance(saved_language, str) and saved_language.strip():
        return saved_language.strip()
    return audio_recognition.resolve_speech_language("ru")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    save_log_event(direction="user", event_type="command_start", content="/start", update=update)

    welcome_text = (
        "Сәлем. Бұл бот енді OCR қолданбайды.\n\n"
        "1) Жай мәтін жіберсеңіз, бот AI жауап қайтарады\n"
        "2) /ai командасы арқылы нақты сұрақ жібере аласыз\n"
        "3) /web командасы интернеттен контекст алып жауап береді\n"
        "4) Voice немесе audio жіберсеңіз, бот оны мәтінге айналдырады және есте сақтайды\n"
        "5) /speak командасы мәтінді дыбыстап береді"
    )
    await update.message.reply_text(welcome_text)
    save_log_event(direction="bot", event_type="welcome_message", content=welcome_text, update=update)


async def speak_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    explicit_text = " ".join(context.args).strip()
    text_to_speak = resolve_text_for_speech(context, explicit_text)
    if not text_to_speak:
        response_text = "Дыбыстауға мәтін жоқ. Әуелі мәтін не audio жіберіңіз, не `/speak мәтін` деп жазыңыз."
        await update.message.reply_text(response_text)
        save_log_event(direction="bot", event_type="speak_error", content=response_text, update=update)
        return

    user_id = str(update.effective_user.id)
    audio_path = BASE_DIR / f"{user_id}_speech.mp3"
    save_log_event(
        direction="user",
        event_type="speak_command",
        content=explicit_text or "[last_result_text]",
        update=update,
        metadata={"tts_lang": DEFAULT_TTS_LANGUAGE},
    )

    try:
        generate_speech(text_to_speak, str(audio_path), language=DEFAULT_TTS_LANGUAGE)
        if not audio_path.exists():
            raise RuntimeError("Speech file was not created.")

        with audio_path.open("rb") as audio_stream:
            await update.message.reply_audio(audio=audio_stream)

        save_log_event(
            direction="bot",
            event_type="speech_reply",
            content="[audio]",
            update=update,
            metadata={"tts_lang": DEFAULT_TTS_LANGUAGE},
        )
    except Exception as exc:
        logger.error("Speech generation error: %s", exc)
        response_text = "Дыбыстық жауап жасау кезінде қате шықты."
        await update.message.reply_text(response_text)
        save_log_event(
            direction="bot",
            event_type="speak_error",
            content=response_text,
            update=update,
            metadata={"error": str(exc), "tts_lang": DEFAULT_TTS_LANGUAGE},
        )
    finally:
        if audio_path.exists():
            audio_path.unlink()


async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    prompt = " ".join(context.args).strip()
    if not prompt:
        response_text = "Қолдану үлгісі: /ai Қазақстан туралы қысқаша айт"
        await update.message.reply_text(response_text)
        save_log_event(direction="bot", event_type="ai_prompt_help", content=response_text, update=update)
        return

    event_id = save_log_event(direction="user", event_type="ai_command", content=prompt, update=update)
    answer = await send_ai_reply(
        update.message,
        prompt,
        str(update.effective_user.id),
        source_event="ai_command",
        chat_id=str(update.effective_chat.id),
        current_event_id=event_id,
    )
    if answer:
        remember_last_text(context, "last_result_text", answer)


async def web_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    prompt = " ".join(context.args).strip()
    if not prompt:
        response_text = "Қолдану үлгісі: /web бүгінгі жаңалықтарды қысқаша айт"
        await update.message.reply_text(response_text)
        save_log_event(direction="bot", event_type="web_prompt_help", content=response_text, update=update)
        return

    event_id = save_log_event(direction="user", event_type="web_command", content=prompt, update=update)
    answer = await send_ai_reply(
        update.message,
        prompt,
        str(update.effective_user.id),
        source_event="web_command",
        chat_id=str(update.effective_chat.id),
        current_event_id=event_id,
        force_web_search=True,
    )
    if answer:
        remember_last_text(context, "last_result_text", answer)


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.message.text:
        return

    prompt = update.message.text.strip()
    if not prompt:
        return

    event_id = save_log_event(direction="user", event_type="text_message", content=prompt, update=update)
    answer = await send_ai_reply(
        update.message,
        prompt,
        str(update.effective_user.id),
        source_event="text_message",
        chat_id=str(update.effective_chat.id),
        current_event_id=event_id,
    )
    if answer:
        remember_last_text(context, "last_result_text", answer)


async def audio_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    telegram_audio = update.message.voice or update.message.audio
    if not telegram_audio:
        return

    user_id = str(update.effective_user.id)
    suffix = ".ogg"
    if update.message.audio and update.message.audio.file_name:
        detected_suffix = Path(update.message.audio.file_name).suffix
        if detected_suffix:
            suffix = detected_suffix

    source_path = BASE_DIR / f"{user_id}_audio{suffix}"
    language = get_user_speech_language(context)
    save_log_event(
        direction="user",
        event_type="audio_upload",
        content="[audio]",
        update=update,
        metadata={"suffix": suffix, "language": language},
    )

    try:
        telegram_file = await telegram_audio.get_file()
        await telegram_file.download_to_drive(str(source_path))

        transcript = audio_recognition.transcribe_audio_file(str(source_path), language=language)
        remember_last_text(context, "last_audio_text", transcript)
        save_log_event(
            direction="user",
            event_type="audio_transcript",
            content=transcript,
            update=update,
            metadata={"language": language},
        )

        transcript_message = f"Танылған мәтін:\n\n{transcript}"
        await update.message.reply_text(transcript_message)
        save_log_event(direction="bot", event_type="audio_transcript_reply", content=transcript_message, update=update)
    except audio_recognition.AudioRecognitionError as exc:
        logger.error("Audio recognition error: %s", exc)
        response_text = str(exc)
        await update.message.reply_text(response_text)
        save_log_event(direction="bot", event_type="audio_error", content=response_text, update=update)
    except Exception as exc:
        logger.error("Audio processing error: %s", exc)
        response_text = "Аудионы өңдеу кезінде қате шықты."
        await update.message.reply_text(response_text)
        save_log_event(
            direction="bot",
            event_type="audio_error",
            content=response_text,
            update=update,
            metadata={"error": str(exc)},
        )
    finally:
        if source_path.exists():
            source_path.unlink()


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.warning("Bot error: %s", context.error)
    log_system_event(
        event_type="app_error",
        content=str(context.error),
        metadata={"update_type": type(update).__name__ if update is not None else "None"},
    )


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ai", ai_command))
    app.add_handler(CommandHandler("web", web_command))
    app.add_handler(CommandHandler("speak", speak_command))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, audio_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    app.add_error_handler(error_handler)
