import asyncio
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote_plus, urlparse

import httpx

from config import (
    BING_SEARCH_URL,
    DEFAULT_COUNTRY_AREA_ID,
    ENABLE_PUBLIC_WEB_SEARCH,
    HH_API_BASE_URL,
    JOB_RESULTS_LIMIT,
    PUBLIC_SEARCH_RESULTS_LIMIT,
    REQUEST_TIMEOUT_SECONDS,
)


EXPERIENCE_TO_HH = {
    "no_experience": "noExperience",
    "one_year": "between1And3",
    "three_plus": "between3And6",
}

EXPERIENCE_LABELS = {
    "no_experience": "Тәжірибе жоқ",
    "one_year": "1 жыл",
    "three_plus": "3+ жыл",
}

WORK_MODE_LABELS = {
    "offline": "Офлайн",
    "online": "Онлайн",
    "hybrid": "Гибрид",
}

_CITY_ALIASES = {
    "almaty": "алматы",
    "astana": "астана",
    "nur sultan": "астана",
    "nursultan": "астана",
    "shymkent": "шымкент",
    "karaganda": "караганда",
    "qaragandy": "караганда",
    "karagandy": "караганда",
    "atyrau": "атырау",
    "aktau": "актау",
    "aktobe": "актобе",
    "aqtobe": "актобе",
    "kostanay": "костанай",
    "qostanay": "костанай",
    "taraz": "тараз",
    "pavlodar": "павлодар",
    "turkistan": "туркестан",
    "kyzylorda": "кызылорда",
    "qyzylorda": "кызылорда",
    "oral": "уральск",
    "uralsk": "уральск",
    "oskemen": "усть каменогорск",
    "ust kamenogorsk": "усть каменогорск",
    "semey": "семей",
}

_PUBLIC_SOURCE_HINTS = (
    {"label": "LinkedIn", "site_query": "linkedin.com/jobs/view", "domain": "linkedin.com"},
    {"label": "Telegram", "site_query": "t.me/s", "domain": "t.me"},
    {"label": "Enbek.kz", "site_query": "enbek.kz", "domain": "enbek.kz"},
    {"label": "Rabota.kz", "site_query": "rabota.kz", "domain": "rabota.kz"},
)

_FIELD_GROUPS = {
    "it": ("it", "python", "developer", "backend", "frontend", "qa", "data", "devops", "software"),
    "marketing": ("marketing", "smm", "brand", "content", "seo", "таргет", "маркет"),
    "education": ("білім", "education", "teacher", "оқыт", "tutor", "methodist"),
    "sales": ("sales", "sale", "продаж", "account", "b2b"),
    "design": ("design", "designer", "ux", "ui", "graphic", "motion"),
}

_AREA_CACHE = None


@dataclass
class JobSearchProfile:
    city: str
    field: str
    experience: str
    work_mode: str
    salary_text: str = ""
    salary_from: Optional[int] = None
    salary_to: Optional[int] = None
    query: str = ""

    @property
    def effective_query(self) -> str:
        return (self.query or self.field or "").strip()


@dataclass
class JobVacancy:
    title: str
    company: str
    summary: str
    salary: str
    apply_text: str
    apply_url: str
    source: str
    is_example: bool = False


def experience_label(value: str) -> str:
    return EXPERIENCE_LABELS.get(value, value or "Көрсетілмеген")


def work_mode_label(value: str) -> str:
    return WORK_MODE_LABELS.get(value, value or "Көрсетілмеген")


def parse_salary_range(raw_value: str) -> Tuple[str, Optional[int], Optional[int]]:
    clean_value = " ".join(raw_value.strip().split())
    if not clean_value:
        return "", None, None

    if _normalize_text(clean_value) in {"откизу", "skip", "жок", "керек емес"}:
        return "", None, None

    numbers = []
    for part in re.findall(r"\d[\d\s]*", clean_value):
        normalized = re.sub(r"\s+", "", part)
        if normalized.isdigit():
            numbers.append(int(normalized))

    if not numbers:
        return clean_value, None, None

    if len(numbers) == 1:
        return clean_value, numbers[0], None

    start, end = sorted(numbers[:2])
    return clean_value, start, end


def build_profile_from_record(record: Dict[str, object], query: str = "") -> JobSearchProfile:
    return JobSearchProfile(
        city=str(record.get("city", "") or ""),
        field=str(record.get("field", "") or ""),
        experience=str(record.get("experience", "") or ""),
        work_mode=str(record.get("work_mode", "") or ""),
        salary_text=str(record.get("salary_text", "") or ""),
        salary_from=_safe_int(record.get("salary_from")),
        salary_to=_safe_int(record.get("salary_to")),
        query=query.strip(),
    )


async def search_jobs(profile: JobSearchProfile, limit: int = JOB_RESULTS_LIMIT) -> List[JobVacancy]:
    normalized_limit = max(3, min(limit, JOB_RESULTS_LIMIT))
    hh_results = await search_hh_jobs(profile, limit=normalized_limit)
    if len(hh_results) >= normalized_limit:
        return hh_results[:normalized_limit]

    if not ENABLE_PUBLIC_WEB_SEARCH:
        return hh_results

    public_results = await search_public_job_links(profile, limit=normalized_limit - len(hh_results))
    return _merge_results(hh_results, public_results)[:normalized_limit]


async def search_hh_jobs(profile: JobSearchProfile, limit: int = JOB_RESULTS_LIMIT) -> List[JobVacancy]:
    params = {
        "text": _build_hh_text(profile),
        "per_page": max(limit * 5, 20),
        "order_by": "publication_time",
    }

    area_id = await _resolve_area_id(profile.city)
    params["area"] = area_id or DEFAULT_COUNTRY_AREA_ID

    experience_value = EXPERIENCE_TO_HH.get(profile.experience)
    if experience_value:
        params["experience"] = experience_value

    if profile.salary_from:
        params["salary"] = profile.salary_from

    if profile.work_mode == "online":
        params["schedule"] = "remote"

    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={"User-Agent": "job-bot/1.0"},
    ) as client:
        response = await client.get("{0}/vacancies".format(HH_API_BASE_URL.rstrip("/")), params=params)
        response.raise_for_status()
        payload = response.json()

    vacancies = []
    for item in payload.get("items", []):
        if not _matches_work_mode(item, profile.work_mode):
            continue
        vacancies.append(_parse_hh_vacancy(item))
        if len(vacancies) >= limit:
            break
    return vacancies


async def search_public_job_links(profile: JobSearchProfile, limit: int = PUBLIC_SEARCH_RESULTS_LIMIT) -> List[JobVacancy]:
    if not ENABLE_PUBLIC_WEB_SEARCH or not profile.effective_query:
        return []

    tasks = [_search_bing_source(profile, source, max(1, limit)) for source in _PUBLIC_SOURCE_HINTS]
    raw_groups = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    seen_urls = set()
    for group in raw_groups:
        if isinstance(group, Exception):
            continue
        for item in group:
            if item.apply_url in seen_urls:
                continue
            seen_urls.add(item.apply_url)
            results.append(item)
            if len(results) >= limit:
                return results

    if len(results) >= limit:
        return results[:limit]

    fallback_items = _build_portal_search_links(profile, limit)
    return _merge_results(results, fallback_items)[:limit]


def build_example_vacancies(profile: JobSearchProfile, limit: int = 3) -> List[JobVacancy]:
    base_salary = _suggest_salary(profile)
    category = _detect_field_group(profile.field)
    templates = {
        "it": [
            ("Junior Python Developer", "Altai Tech", "API жазу, bug fix жасау және mentor-мен бірге backend дамыту."),
            ("QA Engineer", "Steppe Soft", "Веб өнімді тестілеу, bug репорт жазу, regression жүргізу."),
            ("Data Analyst", "Qadam Analytics", "SQL есебі, dashboard жаңарту, бизнеске қысқа insight беру."),
        ],
        "marketing": [
            ("SMM Manager", "Nova Media", "Контент жоспарлау, reels идеялары және жарнама талдауы."),
            ("Performance Marketer", "Growth Lab", "Meta/Google Ads баптау және CPA төмендету."),
            ("Content Manager", "Brand Pulse", "Мәтін, контент-күнтізбе және аудиториямен жұмыс."),
        ],
        "education": [
            ("Онлайн оқытушы", "Bilim Hub", "Сабақ өткізу, материал дайындау және студент прогресін бақылау."),
            ("Методист", "Orken Academy", "Курс құрылымын жасау және оқу бағдарламасын жақсарту."),
            ("Тьютор", "Zerde School", "Жеке сабақ, кері байланыс және үй тапсырмасын тексеру."),
        ],
        "sales": [
            ("Sales Manager", "Asyl Trade", "Жаңа клиент табу, қоңырау және мәміле жабу."),
            ("Account Manager", "Nomad B2B", "Қолданыстағы клиенттермен байланыс және upsell."),
            ("Lead Manager", "Jet Sales", "Лидтерді сүзу және алғашқы байланыс орнату."),
        ],
        "design": [
            ("UI Designer", "Alem Product", "Веб интерфейс, макет және design system-пен жұмыс."),
            ("Graphic Designer", "Bright Studio", "Креатив, баннер және social media визуалдары."),
            ("Motion Designer", "Frame Lab", "Қысқа роликтер мен анимация дайындау."),
        ],
        "general": [
            ("{0} маманы".format(profile.field or "Жоба"), "Qadam Group", "Негізгі операцияларға қолдау көрсету және командамен жұмыс."),
            ("Кіші маман", "Bastau Team", "Құжат, есеп және күнделікті процестерге көмектесу."),
            ("Координатор", "Orda Works", "Тапсырмаларды жинақтау және нәтиже бақылау."),
        ],
    }

    selected = templates.get(category, templates["general"])[:max(3, limit)]
    results = []
    for index, (title, company, summary) in enumerate(selected[:limit], start=1):
        results.append(
            JobVacancy(
                title=title,
                company=company,
                summary=_append_mode_and_city(summary, profile),
                salary=_format_salary_range(base_salary[0] + (index - 1) * 40000, base_salary[1] + (index - 1) * 60000),
                apply_text="Бұл мысал. Ұқсас вакансияны HH.kz немесе LinkedIn арқылы іздеп, резюмеңізді бейімдеп жіберіңіз.",
                apply_url="",
                source="Мысал вакансия",
                is_example=True,
            )
        )
    return results


def profile_summary(profile: JobSearchProfile) -> str:
    return (
        "Қала: {0}\n"
        "Сала: {1}\n"
        "Тәжірибе: {2}\n"
        "Формат: {3}\n"
        "Жалақы: {4}"
    ).format(
        profile.city or "Көрсетілмеген",
        profile.field or "Көрсетілмеген",
        experience_label(profile.experience),
        work_mode_label(profile.work_mode),
        profile.salary_text or "Көрсетілмеген",
    )


def _append_mode_and_city(summary: str, profile: JobSearchProfile) -> str:
    details = []
    if profile.city:
        details.append("Қала: {0}".format(profile.city))
    if profile.work_mode:
        details.append("Формат: {0}".format(work_mode_label(profile.work_mode)))
    if not details:
        return summary
    return "{0} {1}.".format(summary.rstrip("."), ". ".join(details))


def _build_hh_text(profile: JobSearchProfile) -> str:
    parts = [profile.effective_query]
    if profile.work_mode == "hybrid":
        parts.append("гибрид")
    if profile.work_mode == "online":
        parts.append("удаленно")
    if profile.city and _normalize_text(profile.city) not in _normalize_text(profile.effective_query):
        parts.append(profile.city)
    return " ".join(part.strip() for part in parts if part and part.strip())


def _parse_hh_vacancy(item: Dict[str, object]) -> JobVacancy:
    employer = item.get("employer") or {}
    salary = item.get("salary") or {}
    snippet = item.get("snippet") or {}
    apply_url = str(item.get("apply_alternate_url") or item.get("alternate_url") or "").strip()
    summary_parts = [
        _clean_html(str(snippet.get("responsibility") or "")),
        _clean_html(str(snippet.get("requirement") or "")),
    ]
    summary = " ".join(part for part in summary_parts if part).strip() or "Қысқаша сипаттама берілмеген."

    return JobVacancy(
        title=str(item.get("name") or "Вакансия"),
        company=str(employer.get("name") or "Компания көрсетілмеген"),
        summary=_truncate_text(summary, 210),
        salary=_format_hh_salary(salary),
        apply_text="Сілтемені ашып, HH арқылы өтініш беріңіз.",
        apply_url=apply_url,
        source="HeadHunter",
        is_example=False,
    )


async def _search_bing_source(profile: JobSearchProfile, source: Dict[str, str], limit: int) -> List[JobVacancy]:
    query = _build_public_query(profile, source["site_query"])
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={"User-Agent": "job-bot/1.0"},
        follow_redirects=True,
    ) as client:
        response = await client.get(BING_SEARCH_URL, params={"q": query, "format": "rss"})
        response.raise_for_status()

    root = ET.fromstring(response.text)
    results = []
    for item in root.findall("./channel/item"):
        link = (item.findtext("link") or "").strip()
        if not _url_matches_domain(link, source["domain"]):
            continue

        title = _clean_html(item.findtext("title") or "")
        description = _clean_html(item.findtext("description") or "")
        if not _is_relevant_public_result(title, description, profile):
            continue

        parsed_title, parsed_company = _split_public_title(title, source["label"])
        results.append(
            JobVacancy(
                title=parsed_title,
                company=parsed_company,
                summary=_truncate_text(description or "Қысқаша сипаттама табылмады.", 210),
                salary="Көрсетілмеген",
                apply_text="Сілтемені ашып, public page арқылы өтініш беріңіз.",
                apply_url=link,
                source=source["label"],
                is_example=False,
            )
        )
        if len(results) >= limit:
            break
    return results


async def _resolve_area_id(city: str) -> str:
    global _AREA_CACHE

    if not city.strip():
        return DEFAULT_COUNTRY_AREA_ID

    if _AREA_CACHE is None:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": "job-bot/1.0"},
        ) as client:
            response = await client.get("{0}/areas".format(HH_API_BASE_URL.rstrip("/")))
            response.raise_for_status()
            payload = response.json()

        _AREA_CACHE = {}
        for item in payload:
            if str(item.get("id")) == DEFAULT_COUNTRY_AREA_ID:
                _index_areas(item.get("areas") or [], _AREA_CACHE)
                break

    return _AREA_CACHE.get(_canonical_city_name(city), "")


def _index_areas(items: Sequence[Dict[str, object]], target: Dict[str, str]) -> None:
    for item in items:
        area_id = str(item.get("id") or "").strip()
        area_name = str(item.get("name") or "").strip()
        if area_id and area_name:
            target[_canonical_city_name(area_name)] = area_id
        nested = item.get("areas") or []
        if nested:
            _index_areas(nested, target)


def _canonical_city_name(value: str) -> str:
    normalized = _normalize_text(value)
    return _CITY_ALIASES.get(normalized, normalized)


def _normalize_text(value: str) -> str:
    translation = str.maketrans({
        "қ": "к",
        "ғ": "г",
        "ә": "а",
        "ө": "о",
        "ү": "у",
        "ұ": "у",
        "ң": "н",
        "һ": "х",
        "і": "и",
        "ё": "е",
    })
    clean_value = value.lower().translate(translation)
    clean_value = re.sub(r"[^a-zа-я0-9\s]+", " ", clean_value)
    return " ".join(clean_value.split())


def _matches_work_mode(item: Dict[str, object], work_mode: str) -> bool:
    schedule = item.get("schedule") or {}
    work_format = item.get("work_format") or []
    schedule_id = str(schedule.get("id") or "")
    format_ids = {str(entry.get("id") or "") for entry in work_format if isinstance(entry, dict)}

    if work_mode == "online":
        return schedule_id == "remote" or "REMOTE" in format_ids
    if work_mode == "hybrid":
        return "HYBRID" in format_ids
    if work_mode == "offline":
        if schedule_id == "remote" or "REMOTE" in format_ids or "HYBRID" in format_ids:
            return False
        return True
    return True


def _build_public_query(profile: JobSearchProfile, site_query: str) -> str:
    parts = ["site:{0}".format(site_query), profile.effective_query]
    if profile.city and profile.work_mode != "online":
        parts.append(profile.city)
    if profile.work_mode == "online":
        parts.append("remote vacancy")
    elif profile.work_mode == "hybrid":
        parts.append("hybrid vacancy")
    else:
        parts.append("vacancy")
    return " ".join(part for part in parts if part)


def _is_relevant_public_result(title: str, description: str, profile: JobSearchProfile) -> bool:
    haystack = _normalize_text("{0} {1}".format(title, description))
    query_tokens = [token for token in _normalize_text(profile.effective_query).split() if len(token) > 2]
    if not query_tokens:
        return True

    matches = sum(1 for token in query_tokens if token in haystack)
    if matches == 0:
        return False

    city_tokens = [token for token in _normalize_text(profile.city).split() if len(token) > 2]
    if city_tokens and profile.work_mode != "online":
        if not any(token in haystack for token in city_tokens):
            return matches >= max(2, len(query_tokens) // 2)
    return True


def _split_public_title(title: str, default_company: str) -> Tuple[str, str]:
    for delimiter in (" | ", " - ", " — ", " :: "):
        if delimiter in title:
            left, right = title.split(delimiter, 1)
            if left.strip() and right.strip():
                return left.strip(), right.strip()
    return title or "Вакансия", default_company


def _url_matches_domain(url: str, domain: str) -> bool:
    if not url:
        return False
    hostname = (urlparse(url).hostname or "").lower()
    return hostname == domain or hostname.endswith(".{0}".format(domain))


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(text).split())


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _format_hh_salary(salary: Dict[str, object]) -> str:
    return _format_salary_range(_safe_int(salary.get("from")), _safe_int(salary.get("to")), str(salary.get("currency") or "").upper() or "KZT")


def _format_salary_range(salary_from: Optional[int], salary_to: Optional[int], currency: str = "KZT") -> str:
    if salary_from and salary_to:
        return "{0} - {1} {2}".format(_format_number(salary_from), _format_number(salary_to), currency)
    if salary_from:
        return "{0}+ {1}".format(_format_number(salary_from), currency)
    if salary_to:
        return "Дейін {0} {1}".format(_format_number(salary_to), currency)
    return "Келісім бойынша"


def _format_number(value: int) -> str:
    return "{0:,}".format(value).replace(",", " ")


def _merge_results(primary: Sequence[JobVacancy], secondary: Sequence[JobVacancy]) -> List[JobVacancy]:
    results = []
    seen_urls = set()
    for vacancy in list(primary) + list(secondary):
        key = vacancy.apply_url or "{0}|{1}|{2}".format(vacancy.title, vacancy.company, vacancy.source)
        if key in seen_urls:
            continue
        seen_urls.add(key)
        results.append(vacancy)
    return results


def _build_portal_search_links(profile: JobSearchProfile, limit: int) -> List[JobVacancy]:
    query = quote_plus(profile.effective_query)
    city = quote_plus(profile.city or "")
    items = [
        JobVacancy(
            title="HeadHunter іздеуі",
            company="HeadHunter",
            summary="Сұрауыңыз бойынша ресми HH.kz іздеу беті.",
            salary="Сайттағы жалақыны қараңыз",
            apply_text="Сілтемені ашып, тікелей вакансияларға өтіңіз.",
            apply_url="https://hh.kz/search/vacancy?text={0}".format(query),
            source="HeadHunter",
        ),
        JobVacancy(
            title="Enbek.kz іздеуі",
            company="Enbek.kz",
            summary="Қазақстандағы ресми еңбек платформасындағы іздеу беті.",
            salary="Сайттағы жалақыны қараңыз",
            apply_text="Сілтемені ашып, сүзгілерді нақтылаңыз.",
            apply_url="https://www.enbek.kz/kk/search/vacancy?prof={0}".format(query),
            source="Enbek.kz",
        ),
        JobVacancy(
            title="LinkedIn Jobs іздеуі",
            company="LinkedIn",
            summary="Public professional network ішіндегі вакансия іздеуі.",
            salary="Сайттағы жалақыны қараңыз",
            apply_text="Сілтемені ашып, open jobs тізімін қараңыз.",
            apply_url="https://www.linkedin.com/jobs/search/?keywords={0}&location={1}".format(query, city),
            source="LinkedIn",
        ),
    ]
    return items[: max(1, limit)]


def _detect_field_group(field: str) -> str:
    normalized = _normalize_text(field)
    for group_name, keywords in _FIELD_GROUPS.items():
        if any(keyword in normalized for keyword in keywords):
            return group_name
    return "general"


def _suggest_salary(profile: JobSearchProfile) -> Tuple[int, int]:
    if profile.salary_from and profile.salary_to:
        return profile.salary_from, profile.salary_to
    if profile.salary_from:
        return profile.salary_from, profile.salary_from + 150000

    defaults = {
        "it": (300000, 500000),
        "marketing": (220000, 380000),
        "education": (180000, 320000),
        "sales": (220000, 420000),
        "design": (240000, 400000),
        "general": (200000, 350000),
    }
    base_from, base_to = defaults.get(_detect_field_group(profile.field), defaults["general"])
    if profile.experience == "one_year":
        return base_from + 60000, base_to + 80000
    if profile.experience == "three_plus":
        return base_from + 150000, base_to + 220000
    return base_from, base_to


def _safe_int(value: object) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
