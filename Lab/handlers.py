"""Telegram update handlers and application wiring."""

import logging
from pathlib import Path

import OCR
import audio_recognition
from ai_service import send_ai_reply
from config import BASE_DIR
from deep_translator import GoogleTranslator
from keyboards import (
    build_ocr_keyboard,
    build_translate_keyboard,
    build_translation_lang_keyboard,
)
from request_logger import log_system_event, save_log_event
from telegram import Message, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


logger = logging.getLogger(__name__)


def get_user_ocr_language(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Read the user's selected OCR language from Telegram user_data."""
    return context.user_data.get("ocr_lang", OCR.DEFAULT_OCR_LANGUAGE)


def get_user_tts_language(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Read the user's selected text-to-speech language from Telegram user_data."""
    return context.user_data.get("tts_lang", OCR.DEFAULT_TTS_LANGUAGE)


def get_user_speech_language(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Resolve the speech-recognition locale for voice and audio messages."""
    saved_language = context.user_data.get("speech_recognition_lang")
    if saved_language:
        return saved_language
    return audio_recognition.resolve_speech_language(get_user_ocr_language(context))


def remember_last_text(context: ContextTypes.DEFAULT_TYPE, key: str, text: str) -> None:
    """Persist the latest text result so follow-up commands can reuse it."""
    context.user_data[key] = text
    context.user_data["last_result_text"] = text


def resolve_text_for_speech(context: ContextTypes.DEFAULT_TYPE, explicit_text: str) -> str:
    """Choose which text should be turned into audio for `/speak`."""
    if explicit_text.strip():
        return explicit_text.strip()

    for key in ("last_result_text", "last_ocr_text", "last_audio_text"):
        stored_text = context.user_data.get(key, "")
        if isinstance(stored_text, str) and stored_text.strip():
            return stored_text.strip()

    return ""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the initial bot help message and the language selection keyboard."""
    if not update.message:
        return

    save_log_event(direction="user", event_type="command_start", content="/start", update=update)

    welcome_text = (
        "Сәлем. Бұл бот суреттен мәтін оқиды, аудионы мәтінге айналдырады және AI-дан жауап ала алады.\n\n"
        "1) OCR үшін фото немесе image файл жіберіңіз\n"
        "2) AI жауабы керек болса, тек /ai командасын қолданыңыз\n"
        "3) Voice немесе audio жіберсеңіз, бот оны тек мәтінге айналдырады\n"
        "4) Дыбыстық жауап керек болса, /speak командасын қолданыңыз"
    )
    await update.message.reply_text(welcome_text)
    save_log_event(direction="bot", event_type="welcome_message", content=welcome_text, update=update)

    language_prompt = "Суреттегі мәтін қай тілде екенін таңдаңыз:"
    await update.message.reply_text(language_prompt, reply_markup=build_ocr_keyboard())
    save_log_event(
        direction="bot",
        event_type="ocr_language_prompt",
        content=language_prompt,
        update=update,
    )


async def get_image_file(message: Message) -> tuple[object | None, str]:
    """Return the Telegram file handle and a safe file suffix for OCR input."""
    if message.photo:
        return await message.photo[-1].get_file(), ".jpg"

    if message.document and (message.document.mime_type or "").startswith("image/"):
        suffix = Path(message.document.file_name or "").suffix or ".jpg"
        return await message.document.get_file(), suffix

    return None, ".jpg"


async def image_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Download a photo or image file, run OCR, and offer translation."""
    if not update.message or not update.effective_user:
        return

    telegram_file, suffix = await get_image_file(update.message)
    if not telegram_file:
        return

    user_id = str(update.effective_user.id)
    image_path = BASE_DIR / f"{user_id}_image{suffix}"
    ocr_language = get_user_ocr_language(context)
    tts_language = get_user_tts_language(context)
    save_log_event(
        direction="user",
        event_type="image_upload",
        content="[image]",
        update=update,
        metadata={"ocr_lang": ocr_language, "tts_lang": tts_language, "suffix": suffix},
    )

    try:
        await telegram_file.download_to_drive(str(image_path))

        if not image_path.exists():
            response_text = "Сурет жүктелмеді. Қайта жіберіп көріңіз."
            await update.message.reply_text(response_text)
            save_log_event(direction="bot", event_type="image_error", content=response_text, update=update)
            return

        text = OCR.text_find(str(image_path), language=ocr_language)
        logger.info("Recognized text from %s: %s", user_id, text)

        if not text.strip():
            response_text = "Мәтін табылмады. Басқа сурет жіберіп көріңіз."
            await update.message.reply_text(response_text)
            save_log_event(direction="bot", event_type="image_ocr_empty", content=response_text, update=update)
            return

        recognized_message = f"Танылған мәтін:\n\n{text}"
        await update.message.reply_text(recognized_message)
        save_log_event(direction="bot", event_type="image_ocr_text", content=text, update=update)

        remember_last_text(context, "last_ocr_text", text)

        translate_prompt = "Мәтінді аудару керек пе?"
        await update.message.reply_text(translate_prompt, reply_markup=build_translate_keyboard())
        save_log_event(direction="bot", event_type="translate_prompt", content=translate_prompt, update=update)
    except (OCR.OCRSetupError, OCR.OCRLanguageError) as exc:
        logger.error("OCR setup error: %s", exc)
        response_text = str(exc)
        await update.message.reply_text(response_text)
        save_log_event(direction="bot", event_type="image_ocr_error", content=response_text, update=update)
    except Exception as exc:
        logger.error("Image processing error: %s", exc)
        response_text = "Суретті өңдеу кезінде қате шықты."
        await update.message.reply_text(response_text)
        save_log_event(
            direction="bot",
            event_type="image_ocr_error",
            content=response_text,
            update=update,
            metadata={"error": str(exc)},
        )
    finally:
        if image_path.exists():
            image_path.unlink()


async def speak_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate audio only when the user explicitly asks for it."""
    if not update.message or not update.effective_user:
        return

    explicit_text = " ".join(context.args).strip()
    text_to_speak = resolve_text_for_speech(context, explicit_text)

    if not text_to_speak:
        response_text = "Дыбыстауға мәтін жоқ. Әуелі сурет немесе audio жіберіңіз, не `/speak мәтін` деп жазыңыз."
        await update.message.reply_text(response_text)
        save_log_event(direction="bot", event_type="speak_error", content=response_text, update=update)
        return

    user_id = str(update.effective_user.id)
    audio_path = BASE_DIR / f"{user_id}_speech.mp3"
    tts_language = get_user_tts_language(context)
    save_log_event(
        direction="user",
        event_type="speak_command",
        content=explicit_text or "[last_result_text]",
        update=update,
        metadata={"tts_lang": tts_language},
    )

    try:
        OCR.generate(text_to_speak, str(audio_path), language=tts_language)
        if not audio_path.exists():
            raise RuntimeError("Speech file was not created.")

        with audio_path.open("rb") as audio_stream:
            await update.message.reply_audio(audio=audio_stream)

        save_log_event(
            direction="bot",
            event_type="speech_reply",
            content="[audio]",
            update=update,
            metadata={"tts_lang": tts_language},
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
            metadata={"error": str(exc), "tts_lang": tts_language},
        )
    finally:
        if audio_path.exists():
            audio_path.unlink()


async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the explicit `/ai ...` command and pass the text to OpenRouter."""
    if not update.message or not update.effective_user:
        return

    prompt = " ".join(context.args).strip()
    if not prompt:
        response_text = "Қолдану үлгісі: /ai Қазақстан туралы қысқаша айт"
        await update.message.reply_text(response_text)
        save_log_event(direction="bot", event_type="ai_prompt_help", content=response_text, update=update)
        return

    save_log_event(direction="user", event_type="ai_command", content=prompt, update=update)
    await send_ai_reply(update.message, prompt, str(update.effective_user.id), source_event="ai_command")


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Treat a regular text message as an AI prompt."""
    if not update.message or not update.effective_user or not update.message.text:
        return

    prompt = update.message.text.strip()
    if not prompt:
        return

    save_log_event(direction="user", event_type="text_message", content=prompt, update=update)
    await send_ai_reply(update.message, prompt, str(update.effective_user.id), source_event="text_message")


async def audio_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Transcribe Telegram voice/audio messages without sending an automatic AI reply."""
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

        transcript_message = f"Танылған мәтін:\n\n{transcript}"
        await update.message.reply_text(transcript_message)
        save_log_event(direction="bot", event_type="audio_transcript", content=transcript, update=update)
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


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process inline keyboard callbacks for language selection and translation."""
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data or ""
    save_log_event(direction="user", event_type="callback_query", content=data, update=update)

    if data.startswith("setlang|"):
        _, ocr_lang, tts_lang = data.split("|")
        context.user_data["ocr_lang"] = ocr_lang
        context.user_data["tts_lang"] = tts_lang
        context.user_data["speech_recognition_lang"] = audio_recognition.resolve_speech_language(ocr_lang)

        response_text = "OCR тілі сақталды. Енді мәтіні бар суретті жіберіңіз."
        await query.edit_message_text(response_text)
        save_log_event(
            direction="bot",
            event_type="ocr_language_set",
            content=response_text,
            update=update,
            metadata={"ocr_lang": ocr_lang, "tts_lang": tts_lang},
        )
        return

    if data == "translate_yes":
        response_text = "Аударма тілін таңдаңыз:"
        await query.edit_message_text(response_text, reply_markup=build_translation_lang_keyboard())
        save_log_event(
            direction="bot",
            event_type="translate_language_prompt",
            content=response_text,
            update=update,
        )
        return

    if data.startswith("lang|"):
        _, lang_code = data.split("|")
        original_text = context.user_data.get("last_ocr_text", "")

        if not original_text:
            response_text = "Аударатын мәтін табылмады."
            await query.edit_message_text(response_text)
            save_log_event(direction="bot", event_type="translation_error", content=response_text, update=update)
            return

        try:
            translated = GoogleTranslator(source="auto", target=lang_code).translate(original_text)
            remember_last_text(context, "last_result_text", translated)
            lang_name = {"ru": "Русский", "en": "English", "tr": "Turkce"}.get(lang_code, lang_code)
            response_text = f"{lang_name} тіліне аударма:\n\n{translated}"
            await query.edit_message_text(response_text)
            save_log_event(
                direction="bot",
                event_type="translation_result",
                content=translated,
                update=update,
                metadata={"target_lang": lang_code},
            )
        except Exception as exc:
            logger.error("Translation error: %s", exc)
            response_text = "Аударма кезінде қате шықты."
            await query.edit_message_text(response_text)
            save_log_event(
                direction="bot",
                event_type="translation_error",
                content=response_text,
                update=update,
                metadata={"target_lang": lang_code, "error": str(exc)},
            )
        return

    if data == "translate_no":
        response_text = "Жарайды. Қажет болса жаңа сурет жіберіңіз немесе /speak қолданыңыз."
        await query.edit_message_text(response_text)
        save_log_event(direction="bot", event_type="translate_skipped", content=response_text, update=update)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unhandled Telegram framework errors into both console and database."""
    logger.warning("Bot error: %s", context.error)
    log_system_event(
        event_type="app_error",
        content=str(context.error),
        metadata={"update_type": type(update).__name__ if update is not None else "None"},
    )


def register_handlers(app: Application) -> None:
    """Attach every command, message handler, and callback to the application."""
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ai", ai_command))
    app.add_handler(CommandHandler("speak", speak_command))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, image_message))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, audio_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_error_handler(error_handler)
