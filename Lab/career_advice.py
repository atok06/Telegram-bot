import re
from typing import Dict, List

from job_search import EXPERIENCE_LABELS, WORK_MODE_LABELS


def build_resume_help(profile: Dict[str, object]) -> str:
    field = str(profile.get("field", "") or "таңдаған сала")
    experience = EXPERIENCE_LABELS.get(str(profile.get("experience", "") or ""), "тәжірибе деңгейіңіз")
    focus = _resume_focus(str(profile.get("experience", "") or ""))

    lines = [
        "Резюме үшін қысқа құрылым:",
        "1. Аты-жөніңіз, телефон, email, LinkedIn не портфолио.",
        "2. Мақсат: {0} бағыты бойынша {1} маман.".format(field, experience),
        "3. Негізгі дағдылар: {0}.".format(", ".join(_skill_keywords(field)[:5])),
        "4. Тәжірибе не жоба: нақты нәтиже көрсетіңіз.",
        "5. Білім, курс, сертификат.",
        "",
        "Негізгі акцент: {0}".format(focus),
    ]
    return "\n".join(lines)


def build_interview_help(profile: Dict[str, object]) -> str:
    questions = _interview_questions(str(profile.get("field", "") or ""))
    lines = ["Сұхбатқа дайындық үшін 5 сұрақ:"]
    for index, question in enumerate(questions[:5], start=1):
        lines.append("{0}. {1}".format(index, question))
    lines.append("")
    lines.append("Кеңес: әр жауапта нақты мысал мен нәтиже айтыңыз.")
    return "\n".join(lines)


def build_skills_help(profile: Dict[str, object]) -> str:
    skills = _skill_keywords(str(profile.get("field", "") or ""))
    experience = str(profile.get("experience", "") or "")
    work_mode = WORK_MODE_LABELS.get(str(profile.get("work_mode", "") or ""), "кез келген формат")

    if experience == "no_experience":
        emphasis = "портфолио, 2-3 шағын жоба және базалық құралдар"
    elif experience == "three_plus":
        emphasis = "leadership, жүйелеу және бизнес әсері"
    else:
        emphasis = "тәжірибені санмен көрсету және құралдарды тереңдету"

    lines = ["Дамытатын дағдылар:"]
    for index, skill in enumerate(skills[:5], start=1):
        lines.append("{0}. {1}".format(index, skill))
    lines.append("")
    lines.append("Фокус: {0}. Қалаған формат: {1}.".format(emphasis, work_mode))
    return "\n".join(lines)


def build_quick_job_tip(profile: Dict[str, object]) -> str:
    experience = str(profile.get("experience", "") or "")
    if experience == "no_experience":
        return "Кеңес: резюмеге курс, pet-project және 1-2 нақты нәтиже қосыңыз."
    if experience == "three_plus":
        return "Кеңес: резюмеде басқарған жобаңыз бен бизнес нәтижені бірінші орынға шығарыңыз."
    return "Кеңес: соңғы тәжірибеңіздегі нәтижені санмен көрсетіңіз."


def _resume_focus(experience: str) -> str:
    if experience == "no_experience":
        return "курс, портфолио, практика және мотивация"
    if experience == "three_plus":
        return "жетістік, жетекшілік және өлшенетін нәтиже"
    return "тәжірибе, құралдар және нақты KPI"


def _interview_questions(field: str) -> List[str]:
    normalized = _normalize_text(field)
    if any(token in normalized for token in ("python", "developer", "it", "backend", "frontend", "qa", "data")):
        return [
            "Соңғы жобаңызда қандай мәселені шештіңіз?",
            "Қай технологиямен сенімді жұмыс істейсіз?",
            "Bug немесе production issue кезінде қалай әрекет етесіз?",
            "Командамен code review не task estimation қалай өтті?",
            "Неге дәл осы позиция сізге қызық?",
        ]
    if any(token in normalized for token in ("marketing", "smm", "brand", "content", "seo")):
        return [
            "Қай каналдан ең жақсы нәтиже алдыңыз?",
            "Қандай KPI-мен жұмыс істедіңіз?",
            "Сәтсіз кампания болды ма, не үйрендіңіз?",
            "Контент жоспарын қалай жасайсыз?",
            "Алғашқы 30 күнде не істер едіңіз?",
        ]
    if any(token in normalized for token in ("білім", "teacher", "оқыт", "education", "tutor")):
        return [
            "Сабақ құрылымын қалай жасайсыз?",
            "Қиын оқушымен қалай жұмыс істейсіз?",
            "Прогресті қалай бағалайсыз?",
            "Онлайн форматта қандай әдіс қолданасыз?",
            "Кері байланысты қалай бересіз?",
        ]
    return [
        "Өзіңіз туралы қысқаша айтып беріңіз.",
        "Неге осы жұмыс сізге қызық?",
        "Күшті жағыңыз қандай?",
        "Қиын жағдайды қалай шештіңіз?",
        "Алғашқы 3 айда қандай нәтиже көрсеткіңіз келеді?",
    ]


def _skill_keywords(field: str) -> List[str]:
    normalized = _normalize_text(field)
    if any(token in normalized for token in ("python", "developer", "it", "backend", "frontend", "qa", "data")):
        return ["Python/JS негіздері", "SQL", "Git", "API түсіну", "Тест жазу", "Ағылшын тілі"]
    if any(token in normalized for token in ("marketing", "smm", "brand", "content", "seo")):
        return ["Copywriting", "Meta/Google Ads", "Analytics", "Canva/Figma", "Контент жоспарлау", "A/B тест"]
    if any(token in normalized for token in ("білім", "teacher", "оқыт", "education", "tutor")):
        return ["Сабақ жоспарлау", "Коммуникация", "Онлайн құралдар", "Бағалау әдісі", "Презентация", "Методика"]
    if any(token in normalized for token in ("sales", "продаж", "account", "b2b")):
        return ["Cold outreach", "CRM", "Negotiation", "Lead qualification", "Follow-up", "Presentation"]
    return ["Коммуникация", "Excel/Google Sheets", "Уақытты басқару", "Аналитика", "Жазбаша сауат", "Ағылшын тілі"]


def _normalize_text(value: str) -> str:
    clean_value = re.sub(r"[^a-zа-я0-9\s]+", " ", value.lower())
    return " ".join(clean_value.split())
