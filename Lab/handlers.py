"""Telegram handlers for the job assistant bot."""

import logging
import re
from typing import Dict, Optional

import request_database
from ai_service import ask_career_ai, any_ai_available
from career_advice import build_interview_help, build_quick_job_tip, build_resume_help, build_skills_help
from job_search import (
    UnsafeJobDataError,
    build_profile_from_record,
    experience_label,
    normalize_text,
    parse_salary_range,
    partition_vacancies,
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
PROFILE_REQUIRED_STEPS = PROFILE_STEPS[:-1]

MENU_JOB_SEARCH = "Вакансия табу"
MENU_PROFILE = "Профиль толтыру"
MENU_RESUME = "Резюме"
MENU_INTERVIEW = "Сұхбат"
MENU_SKILLS = "Дағдылар"
MENU_WEB = "Web іздеу"
MENU_AI = "AI кеңес"
MENU_HELP = "Көмек"

SKIP_SALARY_VALUES = {"өткізу", "откізу", "skip", "жоқ", "керек емес"}

CANCEL_FLOW_PHRASES = {
    "болды",
    "жап",
    "жаба сал",
    "таста",
    "тоқта",
    "токта",
    "cancel",
    "stop",
    "отмена",
    "керек емес",
    "не надо",
    "не нужно",
}

CITY_CANONICAL = {
    "алматы": "Алматы",
    "almaty": "Алматы",
    "астана": "Астана",
    "astana": "Астана",
    "nursultan": "Астана",
    "nur sultan": "Астана",
    "шымкент": "Шымкент",
    "shymkent": "Шымкент",
    "караганда": "Қарағанды",
    "қарағанды": "Қарағанды",
    "karaganda": "Қарағанды",
    "qaragandy": "Қарағанды",
    "атырау": "Атырау",
    "atyrau": "Атырау",
    "актау": "Ақтау",
    "aktau": "Ақтау",
    "актобе": "Ақтөбе",
    "ақтөбе": "Ақтөбе",
    "aktobe": "Ақтөбе",
    "aqtobe": "Ақтөбе",
    "костанай": "Қостанай",
    "қостанай": "Қостанай",
    "kostanay": "Қостанай",
    "qostanay": "Қостанай",
    "павлодар": "Павлодар",
    "pavlodar": "Павлодар",
    "тараз": "Тараз",
    "taraz": "Тараз",
    "кызылорда": "Қызылорда",
    "қызылорда": "Қызылорда",
    "kyzylorda": "Қызылорда",
    "qyzylorda": "Қызылорда",
    "семей": "Семей",
    "semey": "Семей",
    "туркестан": "Түркістан",
    "түркістан": "Түркістан",
    "turkistan": "Түркістан",
    "орал": "Орал",
    "oral": "Орал",
    "уральск": "Орал",
    "uralsk": "Орал",
}

FIELD_KEYWORDS = {
    "IT": ("it", "айти", "developer", "backend", "frontend", "python", "java", "qa", "devops", "data", "ml"),
    "Маркетинг": ("маркетинг", "marketing", "smm", "target", "таргет", "seo", "контент", "brand"),
    "Білім": ("білім", "education", "мұғалім", "мугалим", "оқыт", "учител", "преподав", "teacher", "tutor"),
    "Сату": ("сату", "sales", "продаж", "sales manager", "account manager"),
    "Дизайн": ("дизайн", "design", "designer", "ux", "ui", "graphic", "motion"),
    "Қаржы": ("қаржы", "каржы", "finance", "финанс", "бухгалтер", "accountant", "audit", "analyst"),
    "HR": ("hr", "recruiter", "рекрутер", "hr manager", "human resources"),
}

GENERIC_CITY_BLOCKLIST = {
    "жумыс",
    "жұмыс",
    "работа",
    "job",
    "vacancy",
    "вакансия",
    "онлайн",
    "офлайн",
    "гибрид",
    "remote",
    "marketing",
    "маркетинг",
    "it",
    "айти",
    "резюме",
    "cv",
    "resume",
}

GENERIC_FIELD_BLOCKLIST = {
    "жумыс",
    "жұмыс",
    "работа",
    "job",
    "vacancy",
    "вакансия",
    "керек",
    "нужно",
    "нужна",
}

UNSAFE_VACANCY_TEXT = (
    "Қате: сенімсіз немесе өтірік вакансия ақпараты анықталды. "
    "Бот ондай хабарландыруды көрсетпейді."
)

NO_RELIABLE_VACANCY_TEXT = (
    "Қазір сенімді вакансия табылмады. Сұрауды нақтылап көріңіз немесе тек ресми сайттарды қолданыңыз."
)


def _matches_phrase(text: str, phrase: str) -> bool:
    wrapped = " {0} ".format(text)
    target = " {0} ".format(phrase)
    return target in wrapped


def _capitalize_value(value: str) -> str:
    clean_value = " ".join(value.strip(" ,.!?").split())
    if not clean_value:
        return ""
    return clean_value[0].upper() + clean_value[1:]


def _looks_like_cancel(text: str) -> bool:
    normalized = normalize_text(text)
    return any(_matches_phrase(normalized, phrase) for phrase in CANCEL_FLOW_PHRASES)


def _looks_like_salary_skip(text: str) -> bool:
    normalized = normalize_text(text)
    return any(_matches_phrase(normalized, phrase) for phrase in SKIP_SALARY_VALUES)


def _extract_numeric_tokens(text: str) -> list[int]:
    values = []
    for chunk in re.findall(r"\d[\d\s]*", text):
        normalized = re.sub(r"\s+", "", chunk)
        if normalized.isdigit():
            values.append(int(normalized))
    return values


def _looks_like_salary_text(text: str, current_step: str) -> bool:
    if current_step == "salary":
        return True

    normalized = normalize_text(text)
    if any(token in normalized for token in ("жалақы", "жалакы", "salary", "айлық", "айлык", "kzt", "тенге", "тг", "мың", "мын")):
        return True

    numbers = _extract_numeric_tokens(text)
    return any(number >= 50000 for number in numbers)


def _city_keyword_matches(normalized: str, keyword: str) -> bool:
    if " " in keyword:
        return _matches_phrase(normalized, keyword)
    return any(word == keyword or word.startswith(keyword) for word in normalized.split())


def _detect_city(text: str, current_step: str) -> str:
    normalized = normalize_text(text)
    for keyword, city in CITY_CANONICAL.items():
        if _city_keyword_matches(normalized, keyword):
            return city

    if current_step != "city":
        return ""

    raw_value = _capitalize_value(text)
    if not raw_value or len(raw_value.split()) > 3:
        return ""
    if any(token in normalized for token in GENERIC_CITY_BLOCKLIST):
        return ""
    if _looks_like_salary_text(text, "") or _detect_experience(text) or _detect_work_mode(text):
        return ""
    return raw_value


def _detect_field(text: str, current_step: str) -> str:
    normalized = normalize_text(text)
    for field_name, keywords in FIELD_KEYWORDS.items():
        if any(_matches_phrase(normalized, keyword) for keyword in keywords):
            return field_name

    if current_step != "field":
        return ""

    raw_value = _capitalize_value(text)
    if not raw_value or len(raw_value.split()) > 5 or re.search(r"\d", raw_value):
        return ""
    if any(token in normalized for token in GENERIC_FIELD_BLOCKLIST):
        return ""
    if _detect_city(text, "") or _detect_experience(text) or _detect_work_mode(text):
        return ""
    return raw_value


def _detect_experience(text: str, current_step: str = "") -> str:
    normalized = normalize_text(text)
    lowered = text.lower()
    if "3+" in lowered or any(token in normalized for token in ("3 plus", "senior")):
        return "three_plus"
    if any(token in normalized for token in ("жок", "нет опыта", "без опыта", "no experience", "junior", "стажер", "intern")):
        return "no_experience"
    if any(token in normalized for token in ("1 3", "middle", "mid level")):
        return "one_year"

    year_matches = re.findall(r"(\d+)\s*(жыл|жылдан|год|года|лет|year)", normalized)
    for number_text, _ in year_matches:
        number = int(number_text)
        if number >= 3:
            return "three_plus"
        if number in (1, 2):
            return "one_year"
        if number == 0:
            return "no_experience"

    if any(token in normalized for token in ("бір жыл", "бир жыл", "1 жыл", "1 год", "1 year")):
        return "one_year"

    if current_step == "experience":
        numbers = _extract_numeric_tokens(text)
        if len(numbers) == 1:
            number = numbers[0]
            if number >= 3:
                return "three_plus"
            if number in (1, 2):
                return "one_year"
            if number == 0:
                return "no_experience"
    return ""


def _detect_work_mode(text: str) -> str:
    normalized = normalize_text(text)
    if any(token in normalized for token in ("гибрид", "hybrid", "аралас")):
        return "hybrid"
    if any(token in normalized for token in ("онлайн", "online", "remote", "удал", "үйден", "уйден", "дистанцион")):
        return "online"
    if any(token in normalized for token in ("офлайн", "offline", "офис", "кеңсе", "кенсе", "onsite", "on site")):
        return "offline"
    return ""


def _extract_profile_hints(answer: str, current_step: str) -> tuple[Dict[str, object], bool]:
    hints: Dict[str, object] = {}

    city = _detect_city(answer, current_step)
    if city:
        hints["city"] = city

    field = _detect_field(answer, current_step)
    if field:
        hints["field"] = field

    experience = _detect_experience(answer, current_step)
    if experience:
        hints["experience"] = experience

    work_mode = _detect_work_mode(answer)
    if work_mode:
        hints["work_mode"] = work_mode

    salary_handled = False
    if current_step == "salary":
        salary_handled = True
        if _looks_like_salary_skip(answer):
            hints["salary_text"] = ""
            hints["salary_from"] = None
            hints["salary_to"] = None
        else:
            salary_text, salary_from, salary_to = parse_salary_range(answer)
            hints["salary_text"] = salary_text
            hints["salary_from"] = salary_from
            hints["salary_to"] = salary_to
    else:
        large_numbers = [number for number in _extract_numeric_tokens(answer) if number >= 50000]
        if large_numbers:
            salary_handled = True
            if len(large_numbers) == 1:
                hints["salary_text"] = str(large_numbers[0])
                hints["salary_from"] = large_numbers[0]
                hints["salary_to"] = None
            else:
                salary_from, salary_to = sorted(large_numbers[:2])
                hints["salary_text"] = "{0}-{1}".format(salary_from, salary_to)
                hints["salary_from"] = salary_from
                hints["salary_to"] = salary_to

    return hints, salary_handled


def _next_profile_step(profile: Dict[str, object], salary_handled: bool) -> str:
    for step in PROFILE_REQUIRED_STEPS:
        if not str(profile.get(step, "") or "").strip():
            return step
    return "" if salary_handled else "salary"


def _fallback_profile_clarification(step: str) -> str:
    prompts = {
        "city": "Қай қалада жұмыс іздейтініңізді бір сөйлеммен жазыңыз. Мысалы: Алматы немесе Астана.",
        "field": "Қай сала керек екенін еркін жаза салыңыз. Мысалы: Python backend, маркетинг, білім.",
        "experience": "Тәжірибеңізді еркін жазыңыз. Мысалы: тәжірибем жоқ, 1 жыл, 3+ жыл.",
        "work_mode": "Жұмыс форматын жазыңыз: онлайн, офлайн, гибрид немесе remote.",
        "salary": "Жалақыны еркін жаза салыңыз. Мысалы: 300000-450000 немесе өткізу.",
    }
    return prompts.get(step, "Жауапты қысқа жаза салыңыз.")


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


def _profile_step_reply_markup(step: str):
    if step == "experience":
        return _experience_keyboard()
    if step == "work_mode":
        return _work_mode_keyboard()
    if step == "salary":
        return _salary_keyboard()
    return ReplyKeyboardRemove()


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
    context.user_data["pending_profile"] = {
        "city": "",
        "field": "",
        "experience": "",
        "work_mode": "",
        "salary_text": "",
        "salary_from": None,
        "salary_to": None,
    }
    context.user_data["salary_handled"] = False


def _cancel_profile_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("profile_step", None)
    context.user_data.pop("pending_profile", None)
    context.user_data.pop("salary_handled", None)


async def _ask_current_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return

    step = context.user_data.get("profile_step", "")
    if step == "city":
        await update.effective_message.reply_text(
            "Қай қалада жұмыс іздейсіз? Еркін жаза беріңіз. Мысалы: Алматы немесе Астанада онлайн IT.",
            reply_markup=_profile_step_reply_markup("city"),
        )
        return
    if step == "field":
        await update.effective_message.reply_text(
            "Қай салада жұмыс іздейсіз? Дайын тізім емес, өз сөзіңізбен жаза беріңіз. Мысалы: Python backend, маркетинг, білім.",
            reply_markup=_profile_step_reply_markup("field"),
        )
        return
    if step == "experience":
        await update.effective_message.reply_text(
            "Тәжірибеңіз қандай? Мысалы: тәжірибем жоқ, 1 жыл, 3+ жыл, junior.",
            reply_markup=_profile_step_reply_markup("experience"),
        )
        return
    if step == "work_mode":
        await update.effective_message.reply_text(
            "Қандай формат керек? Мысалы: онлайн, офлайн, гибрид, remote.",
            reply_markup=_profile_step_reply_markup("work_mode"),
        )
        return
    if step == "salary":
        await update.effective_message.reply_text(
            "Қалаған жалақыны еркін жазыңыз. Мысалы: 250000-400000 немесе 350000+. Қаламасаңыз, `Өткізу` деп жазыңыз.",
            reply_markup=_profile_step_reply_markup("salary"),
        )


async def _profile_clarification(
    update: Update,
    step: str,
    answer: str,
    pending_profile: Dict[str, object],
) -> None:
    if not update.effective_message:
        return

    text = _fallback_profile_clarification(step)
    if any_ai_available():
        try:
            text = await ask_career_ai(
                prompt=(
                    "The user is filling a short job-search profile in Telegram. "
                    "One field is still missing. Ask only one short follow-up question in Kazakh. "
                    "Do not give a rigid template list. Say they can answer freely in one sentence.\n\n"
                    "Missing field: {0}\n"
                    "User answer: {1}"
                ).format(step, answer),
                profile=pending_profile,
            )
        except Exception as exc:
            logger.warning("Profile clarification AI failed, using fallback: %s", exc)

    await update.effective_message.reply_text(text, reply_markup=_profile_step_reply_markup(step))


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
    welcome_text = (
        "Мен сізге өзіңізге сай жұмысты тез табуға көмектесемін.\n"
        "Алдымен 5 қысқа сұрақ қоямын. Қаласаңыз, бәрін бір сөйлеммен де жаза аласыз."
    )
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
        "/search <сұрау> - web және public сілтемелер\n"
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
    await update.message.reply_text(
        "Профильді жаңартамыз. Жауапты еркін жаза беріңіз, бот маңызды мәліметті өзі бөліп алады."
    )
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
        raw_results = await search_public_job_links(profile)
    except Exception as exc:
        logger.exception("Public search failed: %s", exc)
        text = "Web іздеу кезінде қате шықты. /jobs командасымен ресми вакансияларды қарап көріңіз."
        await update.message.reply_text(text, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="search_error", content=text, update=update, metadata={"error": str(exc)})
        return

    direct_results = [item for item in raw_results if item.is_direct_listing]
    portal_results = [item for item in raw_results if not item.is_direct_listing]
    safe_direct, unsafe_direct = partition_vacancies(direct_results)
    vacancies = safe_direct + portal_results

    if not vacancies and unsafe_direct:
        await update.message.reply_text(UNSAFE_VACANCY_TEXT, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="search_unsafe_results", content=UNSAFE_VACANCY_TEXT, update=update)
        return

    if not vacancies:
        await update.message.reply_text(NO_RELIABLE_VACANCY_TEXT, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="search_no_results", content=NO_RELIABLE_VACANCY_TEXT, update=update)
        return

    response = _format_vacancies_message("Public web және ресми сілтемелер:", vacancies, False)
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
    salary_handled = bool(context.user_data.get("salary_handled", False))

    if not step:
        _cancel_profile_flow(context)
        return

    if _looks_like_cancel(answer) and not (step == "salary" and _looks_like_salary_skip(answer)):
        _cancel_profile_flow(context)
        text = "Анкетаны тоқтаттым. Енді еркін сұрақ жаза аласыз немесе /profile деп қайта бастай аласыз."
        await update.message.reply_text(text, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="profile_cancelled_by_text", content=text, update=update)
        return

    hints, salary_answer_handled = _extract_profile_hints(answer, step)
    pending_profile.update(hints)
    salary_handled = salary_handled or salary_answer_handled

    current_value = str(pending_profile.get(step, "") or "").strip()
    if step == "salary" and salary_answer_handled:
        current_value = "handled"

    if not current_value:
        context.user_data["pending_profile"] = pending_profile
        context.user_data["salary_handled"] = salary_handled
        await _profile_clarification(update, step, answer, pending_profile)
        return

    next_step = _next_profile_step(pending_profile, salary_handled)
    context.user_data["pending_profile"] = pending_profile
    context.user_data["salary_handled"] = salary_handled
    context.user_data["profile_step"] = next_step

    if next_step:
        await _ask_current_question(update, context)
        return

    if not _is_profile_complete(pending_profile):
        _cancel_profile_flow(context)
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
    except UnsafeJobDataError:
        await update.effective_message.reply_text(UNSAFE_VACANCY_TEXT, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="jobs_unsafe_results", content=UNSAFE_VACANCY_TEXT, update=update)
        return
    except Exception as exc:
        logger.exception("Job search failed: %s", exc)
        text = "Вакансия іздеу кезінде қате шықты. Кейінірек қайталап көріңіз."
        await update.effective_message.reply_text(text, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="jobs_error", content=text, update=update, metadata={"error": str(exc)})
        return

    if not vacancies:
        await update.effective_message.reply_text(NO_RELIABLE_VACANCY_TEXT, reply_markup=_main_menu_keyboard())
        save_log_event(direction="bot", event_type="job_no_reliable_results", content=NO_RELIABLE_VACANCY_TEXT, update=update)
        return

    response = _format_vacancies_message("Сізге сай сенімді вакансиялар:", vacancies, True, build_quick_job_tip(profile_record))
    await update.effective_message.reply_text(response, reply_markup=_main_menu_keyboard(), disable_web_page_preview=True)
    save_log_event(
        direction="bot",
        event_type="job_results",
        content=response,
        update=update,
        metadata={"results": len(vacancies), "query": profile.effective_query},
    )


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
                "If the user message contains fake vacancy or client details, return a short error instead.\n\n"
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
        lines.append("Өтініш: {0} {1}".format(vacancy.apply_text, vacancy.apply_url))
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
