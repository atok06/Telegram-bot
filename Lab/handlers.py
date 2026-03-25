"""Telegram handlers for the job assistant bot."""

import logging
from typing import Dict, Optional

import request_database
from ai_service import ask_career_ai, any_ai_available
from career_advice import build_interview_help, build_quick_job_tip, build_resume_help, build_skills_help
from job_search import (
    build_example_vacancies,
    build_profile_from_record,
    experience_label,
    parse_salary_range,
    profile_summary,
    search_jobs,
    search_public_job_links,
    work_mode_label,
)
from request_logger import log_system_event, save_log_event
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


logger = logging.getLogger(__name__)

PROFILE_STEPS = ("city", "field", "experience", "work_mode", "salary")

EXPERIENCE_OPTIONS = {
    "жоқ": "no_experience",
    "жок": "no_experience",
    "нет": "no_experience",
    "no": "no_experience",
    "1 жыл": "one_year",
    "1": "one_year",
    "бір жыл": "one_year",
    "one year": "one_year",
    "3+ жыл": "three_plus",
    "3+": "three_plus",
    "3 жыл": "three_plus",
    "3 жылдан жоғары": "three_plus",
}

WORK_MODE_OPTIONS = {
    "офлайн": "offline",
    "offline": "offline",
    "онлайн": "online",
    "online": "online",
    "удаленно": "online",
    "гибрид": "hybrid",
    "hybrid": "hybrid",
}

MENU_JOB_SEARCH = "Вакансия табу"
MENU_PROFILE = "Профиль толтыру"
MENU_RESUME = "Резюме"
MENU_INTERVIEW = "Сұхбат"
MENU_SKILLS = "Дағдылар"
MENU_WEB = "Web іздеу"
MENU_AI = "AI кеңес"
MENU_HELP = "Көмек"

SKIP_SALARY_VALUES = {"өткізу", "откізу", "skip", "жоқ", "керек емес"}


def _main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [MENU_JOB_SEARCH, MENU_PROFILE],
            [MENU_RESUME, MENU_INTERVIEW],
            [MENU_SKILLS, MENU_WEB],
            [MENU_AI, MENU_HELP],
        ],
        resize_keyboard=True,
    )


def _experience_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["Жоқ", "1 жыл", "3+ жыл"]], resize_keyboard=True, one_time_keyboard=True)


def _work_mode_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["Офлайн", "Онлайн", "Гибрид"]], resize_keyboard=True, one_time_keyboard=True)


def _salary_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["Өткізу"]], resize_keyboard=True, one_time_keyboard=True)


def _get_user_profile(update: Update) -> Dict[str, object]:
    if not update.effective_user or not update.effective_chat:
        return {}
    return request_database.get_user_profile(
        user_id=str(update.effective_user.id),
        chat_id=str(update.effective_chat.id),
    )


def _save_user_profile(update: Update, profile: Dict[str, object]) -> None:
    if not update.effective_user or not update.effective_chat:
        return
    request_database.save_user_profile(
        user_id=str(update.effective_user.id),
        chat_id=str(update.effective_chat.id),
        city=str(profile.get("city", "") or ""),
        field=str(profile.get("field", "") or ""),
        experience=str(profile.get("experience", "") or ""),
        work_mode=str(profile.get("work_mode", "") or ""),
        salary_text=str(profile.get("salary_text", "") or ""),
        salary_from=profile.get("salary_from"),
        salary_to=profile.get("salary_to"),
    )


def _is_profile_complete(profile: Dict[str, object]) -> bool:
    return all(str(profile.get(field_name, "") or "").strip() for field_name in ("city", "field", "experience", "work_mode"))


def _begin_profile_flow(context: ContextTypes.DEFAULT_TYPE, existing_profile: Optional[Dict[str, object]] = None) -> None:
    context.user_data["profile_step"] = PROFILE_STEPS[0]
    context.user_data["pending_profile"] = dict(existing_profile or {})


def _cancel_profile_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("profile_step", None)
    context.user_data.pop("pending_profile", None)


async def _ask_current_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return

    step = context.user_data.get("profile_step", "")
    if step == "city":
        await update.effective_message.reply_text("Қай қалада жұмыс іздейсіз?", reply_markup=ReplyKeyboardRemove())
        return
    if step == "field":
        await update.effective_message.reply_text(
            "Қай салада жұмыс іздейсіз? Мысалы: IT, маркетинг, білім.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if step == "experience":
        await update.effective_message.reply_text("Тәжірибеңіз қандай?", reply_markup=_experience_keyboard())
        return
    if step == "work_mode":
        await update.effective_message.reply_text("Қандай формат керек?", reply_markup=_work_mode_keyboard())
        return
    if step == "salary":
        await update.effective_message.reply_text(
            "Қалаған жалақы диапазонын жазыңыз. Мысалы: 250000-400000. Қаламасаңыз, `Өткізу` деп жазыңыз.",
            reply_markup=_salary_keyboard(),
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    save_log_event(direction="user", event_type="command_start", content="/start", update=update)
    existing_profile = _get_user_profile(update)
    if _is_profile_complete(existing_profile):
        profile = build_profile_from_record(existing_profile)
        text = (
            "Мен жұмыс іздеуге көмектесемін.\n\n"
            "Сақталған профиліңіз:\n{0}\n\n"
            "Дайын командалар:\n"
            "/jobs - сай вакансиялар\n"
            "/search - web пен соц-желі сілтемелері\n"
            "/resume - резюме көмегі\n"
            "/interview - сұхбат сұрақтары\n"
            "/skills - дамыту керек дағдылар\n"
            "/ai - AI career кеңес\n"
            "/profile - профильді жаңарту"
        ).format(profile_summary(profile))
        await update.message.reply_text(text, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="welcome_existing_profile", content=text, update=update)
        return

    _begin_profile_flow(context, existing_profile)
    welcome_text = "Мен сізге өзіңізге сай жұмысты тез табуға көмектесемін.\nАлдымен 5 қысқа сұрақ қоямын."
    await update.message.reply_text(welcome_text, reply_markup=ReplyKeyboardRemove())
    save_log_event(direction="bot", event_type="welcome_new_profile", content=welcome_text, update=update)
    await _ask_current_question(update, context)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    save_log_event(direction="user", event_type="command_help", content="/help", update=update)
    help_text = (
        "Командалар:\n"
        "/profile - профиль толтыру не жаңарту\n"
        "/jobs - профиліңізге сай вакансиялар\n"
        "/search <сұрау> - web және public соц-желі сілтемелері\n"
        "/resume - резюме көмегі\n"
        "/interview - сұхбат сұрақтары\n"
        "/skills - дамыту керек дағдылар\n"
        "/ai <сұрақ> - AI-ден career кеңес\n"
        "/cancel - анкетаны тоқтату"
    )
    await update.message.reply_text(help_text, reply_markup=_main_menu_keyboard())
    save_log_event(direction="bot", event_type="help_message", content=help_text, update=update)


async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    prompt = " ".join(context.args).strip()
    save_log_event(direction="user", event_type="command_ai", content=prompt or "/ai", update=update)

    if not prompt:
        text = "Мысалы: /ai менің резюмемді junior backend позициясына қалай жақсартамын?"
        await update.message.reply_text(text, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="ai_help", content=text, update=update)
        return

    await _reply_with_ai_chat(update, prompt, event_type="ai_chat")


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    save_log_event(direction="user", event_type="command_profile", content="/profile", update=update)
    _begin_profile_flow(context, _get_user_profile(update))
    await update.message.reply_text("Профильді жаңартамыз. Жауаптарыңыз қысқа болса жеткілікті.")
    await _ask_current_question(update, context)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    _cancel_profile_flow(context)
    text = "Анкета тоқтатылды. Қайта бастау үшін /profile деп жазыңыз."
    await update.message.reply_text(text, reply_markup=_main_menu_keyboard())
    save_log_event(direction="bot", event_type="profile_cancelled", content=text, update=update)


async def jobs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    query = " ".join(context.args).strip()
    save_log_event(direction="user", event_type="command_jobs", content=query or "/jobs", update=update)
    await _run_job_search(update, query=query)


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    query = " ".join(context.args).strip()
    save_log_event(direction="user", event_type="command_search", content=query or "/search", update=update)
    profile_record = _get_user_profile(update)
    if not _is_profile_complete(profile_record) and not query:
        text = "Алдымен /profile арқылы қысқа профиль толтырыңыз немесе /search Python developer Almaty сияқты жазыңыз."
        await update.message.reply_text(text, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="search_missing_profile", content=text, update=update)
        return

    profile = build_profile_from_record(profile_record, query=query)
    await update.message.reply_text("Public web көздерден іздеп жатырмын...", reply_markup=_main_menu_keyboard())
    try:
        vacancies = await search_public_job_links(profile)
    except Exception as exc:
        logger.exception("Public search failed: %s", exc)
        text = "Web іздеу кезінде қате шықты. /jobs командасымен ресми вакансияларды қарап көріңіз."
        await update.message.reply_text(text, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="search_error", content=text, update=update, metadata={"error": str(exc)})
        return

    if not vacancies:
        text = "Ашық индекстелген web/соц сілтемелер табылмады. /jobs командасын қолданып көріңіз."
        await update.message.reply_text(text, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="search_no_results", content=text, update=update)
        return

    response = _format_vacancies_message("Public web және соц-желі нәтижелері:", vacancies, False)
    await update.message.reply_text(response, reply_markup=_main_menu_keyboard(), disable_web_page_preview=True)
    save_log_event(
        direction="bot",
        event_type="search_results",
        content=response,
        update=update,
        metadata={"results": len(vacancies), "query": profile.effective_query},
    )


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    save_log_event(direction="user", event_type="command_resume", content="/resume", update=update)
    profile = _get_user_profile(update)
    if not _is_profile_complete(profile):
        text = "Резюме кеңесі дәл шығуы үшін алдымен /profile толтырыңыз."
        await update.message.reply_text(text, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="resume_missing_profile", content=text, update=update)
        return

    response = await _build_ai_or_fallback_response(
        profile=profile,
        prompt=(
            "User asks for resume help. Give a short improved resume structure, "
            "what to emphasize for the user's profile, and 3 quick fixes."
        ),
        fallback_text=build_resume_help(profile),
    )
    await update.message.reply_text(response, reply_markup=_main_menu_keyboard())
    save_log_event(direction="bot", event_type="resume_help", content=response, update=update)


async def interview_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    save_log_event(direction="user", event_type="command_interview", content="/interview", update=update)
    profile = _get_user_profile(update)
    if not _is_profile_complete(profile):
        text = "Сұхбат сұрақтары нақты болу үшін алдымен /profile толтырыңыз."
        await update.message.reply_text(text, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="interview_missing_profile", content=text, update=update)
        return

    response = await _build_ai_or_fallback_response(
        profile=profile,
        prompt=(
            "User asks for interview preparation. Give 5 likely questions for this profile "
            "and a short answer strategy."
        ),
        fallback_text=build_interview_help(profile),
    )
    await update.message.reply_text(response, reply_markup=_main_menu_keyboard())
    save_log_event(direction="bot", event_type="interview_help", content=response, update=update)


async def skills_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    save_log_event(direction="user", event_type="command_skills", content="/skills", update=update)
    profile = _get_user_profile(update)
    if not _is_profile_complete(profile):
        text = "Дағды кеңесі нақты болу үшін алдымен /profile толтырыңыз."
        await update.message.reply_text(text, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="skills_missing_profile", content=text, update=update)
        return

    response = await _build_ai_or_fallback_response(
        profile=profile,
        prompt=(
            "User asks what skills to develop. Give 5 skills ordered by priority, "
            "plus one short learning plan for the next 30 days."
        ),
        fallback_text=build_skills_help(profile),
    )
    await update.message.reply_text(response, reply_markup=_main_menu_keyboard())
    save_log_event(direction="bot", event_type="skills_help", content=response, update=update)


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if not text:
        return

    save_log_event(direction="user", event_type="text_message", content=text, update=update)

    if context.user_data.get("profile_step"):
        await _handle_profile_answer(update, context, text)
        return

    if text == MENU_JOB_SEARCH:
        await _run_job_search(update)
        return
    if text == MENU_PROFILE:
        await profile_command(update, context)
        return
    if text == MENU_RESUME:
        await resume_command(update, context)
        return
    if text == MENU_INTERVIEW:
        await interview_command(update, context)
        return
    if text == MENU_SKILLS:
        await skills_command(update, context)
        return
    if text == MENU_WEB:
        await search_command(update, context)
        return
    if text == MENU_AI:
        await _reply_with_ai_chat(update, "Маған мансап бойынша жеке кеңес бер", event_type="ai_chat_menu")
        return
    if text == MENU_HELP:
        await help_command(update, context)
        return

    lowered = text.lower()
    if any(word in lowered for word in ("резюме", "resume", "cv")):
        await resume_command(update, context)
        return
    if any(word in lowered for word in ("сұхбат", "сухбат", "interview")):
        await interview_command(update, context)
        return
    if any(word in lowered for word in ("дағды", "дагды", "skills", "skill")):
        await skills_command(update, context)
        return
    if any(word in lowered for word in ("жұмыс", "жумыс", "вакансия", "vacancy", "job")):
        await _run_job_search(update, query=text)
        return

    await _reply_with_ai_chat(update, text, event_type="ai_chat")


async def _handle_profile_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, answer: str) -> None:
    if not update.message:
        return

    pending_profile = dict(context.user_data.get("pending_profile", {}))
    step = str(context.user_data.get("profile_step", "") or "")

    if step == "city":
        pending_profile["city"] = answer
        next_step = "field"
    elif step == "field":
        pending_profile["field"] = answer
        next_step = "experience"
    elif step == "experience":
        normalized = EXPERIENCE_OPTIONS.get(answer.strip().lower())
        if not normalized:
            await update.message.reply_text("Таңдаңыз: Жоқ, 1 жыл, 3+ жыл.", reply_markup=_experience_keyboard())
            return
        pending_profile["experience"] = normalized
        next_step = "work_mode"
    elif step == "work_mode":
        normalized = WORK_MODE_OPTIONS.get(answer.strip().lower())
        if not normalized:
            await update.message.reply_text("Таңдаңыз: Офлайн, Онлайн, Гибрид.", reply_markup=_work_mode_keyboard())
            return
        pending_profile["work_mode"] = normalized
        next_step = "salary"
    elif step == "salary":
        normalized_answer = answer.strip().lower()
        if normalized_answer in SKIP_SALARY_VALUES:
            salary_text, salary_from, salary_to = "", None, None
        else:
            salary_text, salary_from, salary_to = parse_salary_range(answer)
        pending_profile["salary_text"] = salary_text
        pending_profile["salary_from"] = salary_from
        pending_profile["salary_to"] = salary_to
        next_step = ""
    else:
        _cancel_profile_flow(context)
        return

    context.user_data["pending_profile"] = pending_profile
    context.user_data["profile_step"] = next_step
    if next_step:
        await _ask_current_question(update, context)
        return

    _save_user_profile(update, pending_profile)
    _cancel_profile_flow(context)

    summary = (
        "Профиль сақталды:\n"
        "Қала: {0}\n"
        "Сала: {1}\n"
        "Тәжірибе: {2}\n"
        "Формат: {3}\n"
        "Жалақы: {4}"
    ).format(
        pending_profile.get("city", "Көрсетілмеген"),
        pending_profile.get("field", "Көрсетілмеген"),
        experience_label(str(pending_profile.get("experience", "") or "")),
        work_mode_label(str(pending_profile.get("work_mode", "") or "")),
        pending_profile.get("salary_text") or "Көрсетілмеген",
    )
    await update.message.reply_text(summary, reply_markup=_main_menu_keyboard())
    save_log_event(direction="bot", event_type="profile_saved", content=summary, update=update)
    await _run_job_search(update)


async def _run_job_search(update: Update, query: str = "") -> None:
    if not update.effective_message:
        return

    profile_record = _get_user_profile(update)
    if not _is_profile_complete(profile_record):
        text = "Алдымен 5 қысқа сұраққа жауап берейік. /profile деп жазыңыз."
        await update.effective_message.reply_text(text, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="jobs_missing_profile", content=text, update=update)
        return

    profile = build_profile_from_record(profile_record, query=query)
    await update.effective_message.reply_text("Сізге сай вакансияларды іздеп жатырмын...", reply_markup=_main_menu_keyboard())

    try:
        vacancies = await search_jobs(profile)
    except Exception as exc:
        logger.exception("Job search failed: %s", exc)
        text = "Вакансия іздеу кезінде қате шықты. Кейінірек қайталап көріңіз."
        await update.effective_message.reply_text(text, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="jobs_error", content=text, update=update, metadata={"error": str(exc)})
        return

    if vacancies:
        response = _format_vacancies_message("Сізге сай 3-5 вакансия:", vacancies, True, build_quick_job_tip(profile_record))
        await update.effective_message.reply_text(response, reply_markup=_main_menu_keyboard(), disable_web_page_preview=True)
        save_log_event(
            direction="bot",
            event_type="job_results",
            content=response,
            update=update,
            metadata={"results": len(vacancies), "query": profile.effective_query},
        )
        return

    examples = build_example_vacancies(profile)
    response = _format_vacancies_message(
        "Нақты live вакансия табылмады. Төменде ұқсас мысалдар:",
        examples,
        True,
        build_quick_job_tip(profile_record),
    )
    await update.effective_message.reply_text(response, reply_markup=_main_menu_keyboard(), disable_web_page_preview=True)
    save_log_event(direction="bot", event_type="job_examples", content=response, update=update, metadata={"query": profile.effective_query})


async def _build_ai_or_fallback_response(profile: Dict[str, object], prompt: str, fallback_text: str) -> str:
    if not any_ai_available():
        return fallback_text

    try:
        return await ask_career_ai(prompt=prompt, profile=profile)
    except Exception as exc:
        logger.warning("AI response failed, using fallback: %s", exc)
        return fallback_text


async def _reply_with_ai_chat(update: Update, prompt: str, event_type: str) -> None:
    if not update.message:
        return

    profile = _get_user_profile(update)
    fallback_text = (
        "Мен мына нәрселерге көмектесемін: вакансия, резюме, сұхбат, дағды.\n"
        "Жылдам бастау үшін /profile немесе /jobs қолданыңыз."
    )

    if not any_ai_available():
        await update.message.reply_text(fallback_text, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="fallback_help", content=fallback_text, update=update)
        return

    try:
        response = await ask_career_ai(
            prompt=(
                "Answer the user's career question briefly and practically. "
                "If useful, include next step suggestions.\n\n"
                "User message:\n{0}"
            ).format(prompt),
            profile=profile,
        )
    except Exception as exc:
        logger.warning("AI chat failed, using fallback: %s", exc)
        response = fallback_text
        event_type = "fallback_help"

    await update.message.reply_text(response, reply_markup=_main_menu_keyboard(), disable_web_page_preview=True)
    save_log_event(direction="bot", event_type=event_type, content=response, update=update)


def _format_vacancies_message(heading: str, vacancies, include_tip: bool, tip: str = "") -> str:
    lines = [heading]
    for index, vacancy in enumerate(vacancies, start=1):
        lines.append("")
        lines.append("{0}. {1}".format(index, vacancy.title))
        lines.append("Компания: {0}".format(vacancy.company))
        lines.append("Қысқаша: {0}".format(vacancy.summary))
        lines.append("Жалақы: {0}".format(vacancy.salary))
        if vacancy.apply_url:
            lines.append("Өтініш: {0} {1}".format(vacancy.apply_text, vacancy.apply_url))
        else:
            lines.append("Өтініш: {0}".format(vacancy.apply_text))
        lines.append("Дереккөз: {0}".format(vacancy.source))

    if include_tip and tip:
        lines.append("")
        lines.append(tip)

    return "\n".join(lines)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.warning("Bot error: %s", context.error)
    log_system_event(
        event_type="app_error",
        content=str(context.error),
        metadata={"update_type": type(update).__name__ if update is not None else "None"},
    )


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ai", ai_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("jobs", jobs_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("resume", resume_command))
    app.add_handler(CommandHandler("interview", interview_command))
    app.add_handler(CommandHandler("skills", skills_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    app.add_error_handler(error_handler)
