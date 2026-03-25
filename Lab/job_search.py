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

TRUSTED_DOMAINS = {
    "hh.kz",
    "hh.ru",
    "linkedin.com",
    "enbek.kz",
    "rabota.kz",
    "t.me",
}

SUSPICIOUS_KEYWORDS = (
    "быстрый заработок",
    "лёгкие деньги",
    "легкие деньги",
    "жеңіл табыс",
    "крипта",
    "crypto",
    "ставки",
    "casino",
    "казино",
    "adult",
    "18+",
    "предоплата",
    "вложение",
    "investment",
    "без собеседования",
    "no interview",
    "whatsapp only",
    "telegram only",
)

CITY_ALIASES = {
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

PUBLIC_SOURCE_HINTS = (
    {"label": "LinkedIn", "site_query": "linkedin.com/jobs/view", "domain": "linkedin.com"},
    {"label": "Telegram", "site_query": "t.me/s", "domain": "t.me"},
    {"label": "Enbek.kz", "site_query": "enbek.kz", "domain": "enbek.kz"},
    {"label": "Rabota.kz", "site_query": "rabota.kz", "domain": "rabota.kz"},
)

AREA_CACHE: Dict[str, str] | None = None


class UnsafeJobDataError(RuntimeError):
    """Raised when only suspicious or obviously unreliable job data is found."""


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
    is_direct_listing: bool = True


def experience_label(value: str) -> str:
    return EXPERIENCE_LABELS.get(value, value or "Көрсетілмеген")


def work_mode_label(value: str) -> str:
    return WORK_MODE_LABELS.get(value, value or "Көрсетілмеген")


def parse_salary_range(raw_value: str) -> Tuple[str, Optional[int], Optional[int]]:
    clean_value = " ".join(raw_value.strip().split())
    if not clean_value:
        return "", None, None

    if normalize_text(clean_value) in {"откизу", "skip", "жок", "керек емес"}:
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
        salary_from=safe_int(record.get("salary_from")),
        salary_to=safe_int(record.get("salary_to")),
        query=query.strip(),
    )


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


async def search_jobs(profile: JobSearchProfile, limit: int = JOB_RESULTS_LIMIT) -> List[JobVacancy]:
    normalized_limit = max(1, min(limit, JOB_RESULTS_LIMIT))
    hh_results = await search_hh_jobs(profile, limit=normalized_limit)
    public_results = []
    if ENABLE_PUBLIC_WEB_SEARCH and len(hh_results) < normalized_limit:
        public_results = await search_public_job_links(
            profile,
            limit=normalized_limit - len(hh_results),
            include_fallback_portals=False,
        )

    direct_results = [item for item in _merge_results(hh_results, public_results) if item.is_direct_listing]
    safe_results, unsafe_results = partition_vacancies(direct_results)

    if safe_results:
        return safe_results[:normalized_limit]
    if unsafe_results:
        raise UnsafeJobDataError("Only suspicious or unreliable vacancies were found.")
    return []


async def search_hh_jobs(profile: JobSearchProfile, limit: int = JOB_RESULTS_LIMIT) -> List[JobVacancy]:
    params = {
        "text": build_hh_text(profile),
        "per_page": max(limit * 5, 20),
        "order_by": "publication_time",
    }

    area_id = await resolve_area_id(profile.city)
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

    vacancies: List[JobVacancy] = []
    for item in payload.get("items", []):
        if not matches_work_mode(item, profile.work_mode):
            continue
        vacancies.append(parse_hh_vacancy(item))
        if len(vacancies) >= limit:
            break
    return vacancies


async def search_public_job_links(
    profile: JobSearchProfile,
    limit: int = PUBLIC_SEARCH_RESULTS_LIMIT,
    *,
    include_fallback_portals: bool = True,
) -> List[JobVacancy]:
    if not ENABLE_PUBLIC_WEB_SEARCH or not profile.effective_query:
        return []

    tasks = [search_bing_source(profile, source, max(1, limit)) for source in PUBLIC_SOURCE_HINTS]
    raw_groups = await asyncio.gather(*tasks, return_exceptions=True)

    results: List[JobVacancy] = []
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

    if results or not include_fallback_portals:
        return results[:limit]

    return build_portal_search_links(profile, limit)


def partition_vacancies(vacancies: Sequence[JobVacancy]) -> Tuple[List[JobVacancy], List[JobVacancy]]:
    safe_items: List[JobVacancy] = []
    unsafe_items: List[JobVacancy] = []
    for vacancy in vacancies:
        if is_safe_vacancy(vacancy):
            safe_items.append(vacancy)
        else:
            unsafe_items.append(vacancy)
    return safe_items, unsafe_items


def is_safe_vacancy(vacancy: JobVacancy) -> bool:
    if not vacancy.title.strip() or not vacancy.company.strip():
        return False

    if vacancy.is_direct_listing and not vacancy.apply_url.strip():
        return False

    if vacancy.apply_url and not url_matches_trusted_domain(vacancy.apply_url):
        return False

    haystack = normalize_text(
        " ".join(
            [
                vacancy.title,
                vacancy.company,
                vacancy.summary,
                vacancy.salary,
                vacancy.apply_text,
                vacancy.apply_url,
            ]
        )
    )
    if any(keyword in haystack for keyword in SUSPICIOUS_KEYWORDS):
        return False

    return True


def build_hh_text(profile: JobSearchProfile) -> str:
    parts = [profile.effective_query]
    if profile.work_mode == "hybrid":
        parts.append("гибрид")
    if profile.work_mode == "online":
        parts.append("удаленно")
    if profile.city and normalize_text(profile.city) not in normalize_text(profile.effective_query):
        parts.append(profile.city)
    return " ".join(part.strip() for part in parts if part and part.strip())


def parse_hh_vacancy(item: Dict[str, object]) -> JobVacancy:
    employer = item.get("employer") or {}
    salary = item.get("salary") or {}
    snippet = item.get("snippet") or {}
    apply_url = str(item.get("apply_alternate_url") or item.get("alternate_url") or "").strip()

    summary_parts = [
        clean_html(str(snippet.get("responsibility") or "")),
        clean_html(str(snippet.get("requirement") or "")),
    ]
    summary = " ".join(part for part in summary_parts if part).strip() or "Қысқаша сипаттама берілмеген."

    return JobVacancy(
        title=str(item.get("name") or "Вакансия"),
        company=str(employer.get("name") or "").strip(),
        summary=truncate_text(summary, 210),
        salary=format_hh_salary(salary),
        apply_text="Сілтемені ашып, HH арқылы өтініш беріңіз.",
        apply_url=apply_url,
        source="HeadHunter",
        is_direct_listing=True,
    )


async def search_bing_source(profile: JobSearchProfile, source: Dict[str, str], limit: int) -> List[JobVacancy]:
    query = build_public_query(profile, source["site_query"])
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={"User-Agent": "job-bot/1.0"},
        follow_redirects=True,
    ) as client:
        response = await client.get(BING_SEARCH_URL, params={"q": query, "format": "rss"})
        response.raise_for_status()

    root = ET.fromstring(response.text)
    results: List[JobVacancy] = []
    for item in root.findall("./channel/item"):
        link = (item.findtext("link") or "").strip()
        if not url_matches_domain(link, source["domain"]):
            continue

        title = clean_html(item.findtext("title") or "")
        description = clean_html(item.findtext("description") or "")
        if not is_relevant_public_result(title, description, profile):
            continue

        parsed_title, parsed_company = split_public_title(title, source["label"])
        results.append(
            JobVacancy(
                title=parsed_title,
                company=parsed_company,
                summary=truncate_text(description or "Қысқаша сипаттама табылмады.", 210),
                salary="Көрсетілмеген",
                apply_text="Сілтемені ашып, public page арқылы өтініш беріңіз.",
                apply_url=link,
                source=source["label"],
                is_direct_listing=True,
            )
        )
        if len(results) >= limit:
            break
    return results


async def resolve_area_id(city: str) -> str:
    global AREA_CACHE

    if not city.strip():
        return DEFAULT_COUNTRY_AREA_ID

    if AREA_CACHE is None:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": "job-bot/1.0"},
        ) as client:
            response = await client.get("{0}/areas".format(HH_API_BASE_URL.rstrip("/")))
            response.raise_for_status()
            payload = response.json()

        AREA_CACHE = {}
        for item in payload:
            if str(item.get("id")) == DEFAULT_COUNTRY_AREA_ID:
                index_areas(item.get("areas") or [], AREA_CACHE)
                break

    return AREA_CACHE.get(canonical_city_name(city), "")


def index_areas(items: Sequence[Dict[str, object]], target: Dict[str, str]) -> None:
    for item in items:
        area_id = str(item.get("id") or "").strip()
        area_name = str(item.get("name") or "").strip()
        if area_id and area_name:
            target[canonical_city_name(area_name)] = area_id
        nested = item.get("areas") or []
        if nested:
            index_areas(nested, target)


def canonical_city_name(value: str) -> str:
    normalized = normalize_text(value)
    return CITY_ALIASES.get(normalized, normalized)


def normalize_text(value: str) -> str:
    translation = str.maketrans(
        {
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
        }
    )
    clean_value = value.lower().translate(translation)
    clean_value = re.sub(r"[^a-zа-я0-9\s]+", " ", clean_value)
    return " ".join(clean_value.split())


def matches_work_mode(item: Dict[str, object], work_mode: str) -> bool:
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


def build_public_query(profile: JobSearchProfile, site_query: str) -> str:
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


def is_relevant_public_result(title: str, description: str, profile: JobSearchProfile) -> bool:
    haystack = normalize_text("{0} {1}".format(title, description))
    query_tokens = [token for token in normalize_text(profile.effective_query).split() if len(token) > 2]
    if not query_tokens:
        return True

    matches = sum(1 for token in query_tokens if token in haystack)
    if matches == 0:
        return False

    city_tokens = [token for token in normalize_text(profile.city).split() if len(token) > 2]
    if city_tokens and profile.work_mode != "online":
        if not any(token in haystack for token in city_tokens):
            return matches >= max(2, len(query_tokens) // 2)
    return True


def split_public_title(title: str, default_company: str) -> Tuple[str, str]:
    for delimiter in (" | ", " - ", " — ", " :: "):
        if delimiter in title:
            left, right = title.split(delimiter, 1)
            if left.strip() and right.strip():
                return left.strip(), right.strip()
    return title or "Вакансия", default_company


def url_matches_domain(url: str, domain: str) -> bool:
    if not url:
        return False
    hostname = (urlparse(url).hostname or "").lower()
    return hostname == domain or hostname.endswith(".{0}".format(domain))


def url_matches_trusted_domain(url: str) -> bool:
    if not url:
        return False
    hostname = (urlparse(url).hostname or "").lower()
    return any(hostname == domain or hostname.endswith(".{0}".format(domain)) for domain in TRUSTED_DOMAINS)


def clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(text).split())


def truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def format_hh_salary(salary: Dict[str, object]) -> str:
    return format_salary_range(
        safe_int(salary.get("from")),
        safe_int(salary.get("to")),
        str(salary.get("currency") or "").upper() or "KZT",
    )


def format_salary_range(salary_from: Optional[int], salary_to: Optional[int], currency: str = "KZT") -> str:
    if salary_from and salary_to:
        return "{0} - {1} {2}".format(format_number(salary_from), format_number(salary_to), currency)
    if salary_from:
        return "{0}+ {1}".format(format_number(salary_from), currency)
    if salary_to:
        return "Дейін {0} {1}".format(format_number(salary_to), currency)
    return "Келісім бойынша"


def format_number(value: int) -> str:
    return "{0:,}".format(value).replace(",", " ")


def build_portal_search_links(profile: JobSearchProfile, limit: int) -> List[JobVacancy]:
    query = quote_plus(profile.effective_query)
    city = quote_plus(profile.city or "")
    items = [
        JobVacancy(
            title="HeadHunter іздеуі",
            company="HeadHunter",
            summary="Сұрауыңыз бойынша ресми HH.kz іздеу беті.",
            salary="Сайттағы жалақыны қараңыз",
            apply_text="Сілтемені ашып, ресми вакансияларды өзіңіз тексеріңіз.",
            apply_url="https://hh.kz/search/vacancy?text={0}".format(query),
            source="HeadHunter",
            is_direct_listing=False,
        ),
        JobVacancy(
            title="Enbek.kz іздеуі",
            company="Enbek.kz",
            summary="Қазақстандағы ресми еңбек платформасындағы іздеу беті.",
            salary="Сайттағы жалақыны қараңыз",
            apply_text="Сілтемені ашып, ресми вакансияларды өзіңіз тексеріңіз.",
            apply_url="https://www.enbek.kz/kk/search/vacancy?prof={0}".format(query),
            source="Enbek.kz",
            is_direct_listing=False,
        ),
        JobVacancy(
            title="LinkedIn Jobs іздеуі",
            company="LinkedIn",
            summary="Public professional network ішіндегі жұмыс іздеу беті.",
            salary="Сайттағы жалақыны қараңыз",
            apply_text="Сілтемені ашып, ресми вакансияларды өзіңіз тексеріңіз.",
            apply_url="https://www.linkedin.com/jobs/search/?keywords={0}&location={1}".format(query, city),
            source="LinkedIn",
            is_direct_listing=False,
        ),
    ]
    return items[: max(1, limit)]


def _merge_results(primary: Sequence[JobVacancy], secondary: Sequence[JobVacancy]) -> List[JobVacancy]:
    results: List[JobVacancy] = []
    seen_urls = set()
    for vacancy in list(primary) + list(secondary):
        key = vacancy.apply_url or "{0}|{1}|{2}".format(vacancy.title, vacancy.company, vacancy.source)
        if key in seen_urls:
            continue
        seen_urls.add(key)
        results.append(vacancy)
    return results


def safe_int(value: object) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
