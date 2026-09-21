import re  # Регулярлы өрнектермен жұмыс жасау үшін
from typing import Dict, List  # Тип аннотациялары үшін

from job_search import EXPERIENCE_LABELS, WORK_MODE_LABELS  # Тәжірибе және жұмыс форматы белгілері


def build_resume_help(profile: Dict[str, object]) -> str:
    # Пайдаланушы профилі негізінде резюме нұсқауын жасау
    field = str(profile.get("field", "") or "таңдаған сала")  # Мамандық саласын алу
    experience = EXPERIENCE_LABELS.get(str(profile.get("experience", "") or ""), "тәжірибе деңгейіңіз")  # Тәжірибе белгісін алу
    focus = _resume_focus(str(profile.get("experience", "") or ""))  # Резюме акцентін анықтау

    lines = [
        "Резюме үшін қысқа құрылым:",  # Тақырып жолы
        "1. Аты-жөніңіз, телефон, email, LinkedIn не портфолио.",  # Байланыс ақпараты
        "2. Мақсат: {0} бағыты бойынша {1} маман.".format(field, experience),  # Кәсіби мақсат
        "3. Негізгі дағдылар: {0}.".format(", ".join(_skill_keywords(field)[:5])),  # Алғашқы 5 дағды
        "4. Тәжірибе не жоба: нақты нәтиже көрсетіңіз.",  # Тәжірибе бөлімі
        "5. Білім, курс, сертификат.",  # Білім бөлімі
        "",  # Бос жол
        "Негізгі акцент: {0}".format(focus),  # Негізгі акцент
    ]
    return "\n".join(lines)  # Барлық жолдарды біріктіріп қайтару


def build_interview_help(profile: Dict[str, object]) -> str:
    # Сұхбатқа дайындық нұсқауын жасау
    questions = _interview_questions(str(profile.get("field", "") or ""))  # Салаға сай сұрақтар алу
    lines = ["Сұхбатқа дайындық үшін 5 сұрақ:"]  # Тақырып жолы
    for index, question in enumerate(questions[:5], start=1):  # Алғашқы 5 сұрақты нөмірлеп қосу
        lines.append("{0}. {1}".format(index, question))  # Нөмірленген сұрақ жолы
    lines.append("")  # Бос жол
    lines.append("Кеңес: әр жауапта нақты мысал мен нәтиже айтыңыз.")  # Қорытынды кеңес
    return "\n".join(lines)  # Барлық жолдарды біріктіріп қайтару


def build_skills_help(profile: Dict[str, object]) -> str:
    # Дамытатын дағдылар нұсқауын жасау
    skills = _skill_keywords(str(profile.get("field", "") or ""))  # Салаға сай дағдылар тізімі
    experience = str(profile.get("experience", "") or "")  # Тәжірибе деңгейін алу
    work_mode = WORK_MODE_LABELS.get(str(profile.get("work_mode", "") or ""), "кез келген формат")  # Жұмыс форматын алу

    if experience == "no_experience":  # Тәжірибесіз жағдай
        emphasis = "портфолио, 2-3 шағын жоба және базалық құралдар"  # Тәжірибесіздерге акцент
    elif experience == "three_plus":  # 3+ жыл тәжірибе
        emphasis = "leadership, жүйелеу және бизнес әсері"  # Тәжірибелілерге акцент
    else:  # Орташа тәжірибе
        emphasis = "тәжірибені санмен көрсету және құралдарды тереңдету"  # Орташаларға акцент

    lines = ["Дамытатын дағдылар:"]  # Тақырып жолы
    for index, skill in enumerate(skills[:5], start=1):  # Алғашқы 5 дағдыны нөмірлеп қосу
        lines.append("{0}. {1}".format(index, skill))  # Нөмірленген дағды жолы
    lines.append("")  # Бос жол
    lines.append("Фокус: {0}. Қалаған формат: {1}.".format(emphasis, work_mode))  # Фокус және жұмыс форматы
    return "\n".join(lines)  # Барлық жолдарды біріктіріп қайтару


def build_quick_job_tip(profile: Dict[str, object]) -> str:
    # Тәжірибе деңгейіне қарай жылдам кеңес беру
    experience = str(profile.get("experience", "") or "")  # Тәжірибе деңгейін алу
    if experience == "no_experience":  # Тәжірибесіз жағдай
        return "Кеңес: резюмеге курс, pet-project және 1-2 нақты нәтиже қосыңыз."  # Тәжірибесіздерге кеңес
    if experience == "three_plus":  # 3+ жыл тәжірибе
        return "Кеңес: резюмеде басқарған жобаңыз бен бизнес нәтижені бірінші орынға шығарыңыз."  # Тәжірибелілерге кеңес
    return "Кеңес: соңғы тәжірибеңіздегі нәтижені санмен көрсетіңіз."  # Орташаларға кеңес


def _resume_focus(experience: str) -> str:
    # Тәжірибе деңгейіне қарай резюме акцентін анықтау
    if experience == "no_experience":  # Тәжірибесіз жағдай
        return "курс, портфолио, практика және мотивация"  # Тәжірибесіздерге акцент
    if experience == "three_plus":  # 3+ жыл тәжірибе
        return "жетістік, жетекшілік және өлшенетін нәтиже"  # Тәжірибелілерге акцент
    return "тәжірибе, құралдар және нақты KPI"  # Орташаларға акцент


def _interview_questions(field: str) -> List[str]:
    # Мамандық саласына қарай сұхбат сұрақтарын таңдау
    normalized = _normalize_text(field)  # Мамандық мәтінін нормализациялау
    if any(token in normalized for token in ("python", "developer", "it", "backend", "frontend", "qa", "data")):  # IT саласы
        return [
            "Соңғы жобаңызда қандай мәселені шештіңіз?",   # Мәселені шешу тәжірибесі
            "Қай технологиямен сенімді жұмыс істейсіз?",    # Техникалық білім
            "Bug немесе production issue кезінде қалай әрекет етесіз?",  # Дағдарысты басқару
            "Командамен code review не task estimation қалай өтті?",      # Команда жұмысы
            "Неге дәл осы позиция сізге қызық?",            # Мотивация
        ]
    if any(token in normalized for token in ("marketing", "smm", "brand", "content", "seo")):  # Маркетинг саласы
        return [
            "Қай каналдан ең жақсы нәтиже алдыңыз?",       # Канал тиімділігі
            "Қандай KPI-мен жұмыс істедіңіз?",              # Өлшем көрсеткіштері
            "Сәтсіз кампания болды ма, не үйрендіңіз?",     # Сәтсіздіктен сабақ
            "Контент жоспарын қалай жасайсыз?",             # Жоспарлау процесі
            "Алғашқы 30 күнде не істер едіңіз?",            # Жоспар және мақсат
        ]
    if any(token in normalized for token in ("білім", "teacher", "оқыт", "education", "tutor")):  # Білім саласы
        return [
            "Сабақ құрылымын қалай жасайсыз?",              # Сабақ жоспарлау
            "Қиын оқушымен қалай жұмыс істейсіз?",          # Қиын жағдайды басқару
            "Прогресті қалай бағалайсыз?",                   # Бағалау тәсілі
            "Онлайн форматта қандай әдіс қолданасыз?",       # Онлайн оқыту
            "Кері байланысты қалай бересіз?",                # Feedback беру
        ]
    return [  # Жалпы салаларға арналған сұрақтар
        "Өзіңіз туралы қысқаша айтып беріңіз.",             # Өзін таныстыру
        "Неге осы жұмыс сізге қызық?",                      # Мотивация
        "Күшті жағыңыз қандай?",                            # Күшті жақтары
        "Қиын жағдайды қалай шештіңіз?",                    # Мәселені шешу
        "Алғашқы 3 айда қандай нәтиже көрсеткіңіз келеді?", # Мақсат қою
    ]


def _skill_keywords(field: str) -> List[str]:
    # Мамандық саласына қарай дағдылар тізімін қайтару
    normalized = _normalize_text(field)  # Мамандық мәтінін нормализациялау
    if any(token in normalized for token in ("python", "developer", "it", "backend", "frontend", "qa", "data")):  # IT саласы
        return ["Python/JS негіздері", "SQL", "Git", "API түсіну", "Тест жазу", "Ағылшын тілі"]
    if any(token in normalized for token in ("marketing", "smm", "brand", "content", "seo")):  # Маркетинг саласы
        return ["Copywriting", "Meta/Google Ads", "Analytics", "Canva/Figma", "Контент жоспарлау", "A/B тест"]
    if any(token in normalized for token in ("білім", "teacher", "оқыт", "education", "tutor")):  # Білім саласы
        return ["Сабақ жоспарлау", "Коммуникация", "Онлайн құралдар", "Бағалау әдісі", "Презентация", "Методика"]
    if any(token in normalized for token in ("sales", "продаж", "account", "b2b")):  # Сату саласы
        return ["Cold outreach", "CRM", "Negotiation", "Lead qualification", "Follow-up", "Presentation"]
    return ["Коммуникация", "Excel/Google Sheets", "Уақытты басқару", "Аналитика", "Жазбаша сауат", "Ағылшын тілі"]  # Жалпы дағдылар


def _normalize_text(value: str) -> str:
    # Мәтінді салыстыру үшін тазалап нормализациялау
    clean_value = re.sub(r"[^a-zа-я0-9\s]+", " ", value.lower())  # Арнайы таңбаларды алып тастау
    return " ".join(clean_value.split())  # Артық бос орындарды тазалап қайтару