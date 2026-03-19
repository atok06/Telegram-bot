from dataclasses import dataclass

import httpx

from config import DUCKDUCKGO_API_URL, ENABLE_WEB_SEARCH, WEB_SEARCH_RESULTS_LIMIT


TIME_SENSITIVE_KEYWORDS = (
    "today",
    "latest",
    "recent",
    "current",
    "news",
    "price",
    "weather",
    "score",
    "schedule",
    "now",
    "lookup",
    "search",
    "web",
    "internet",
    "бүгін",
    "соңғы",
    "қазіргі",
    "қазір",
    "жаңалық",
    "баға",
    "ізде",
    "іздеп",
    "интернет",
)


@dataclass(slots=True)
class WebSearchResult:
    title: str
    snippet: str
    url: str


def should_use_web_search(prompt: str, force_web_search: bool = False) -> bool:
    if force_web_search:
        return True
    if not ENABLE_WEB_SEARCH:
        return False

    normalized = prompt.strip().lower()
    return any(keyword in normalized for keyword in TIME_SENSITIVE_KEYWORDS)


def _append_result(
    results: list[WebSearchResult],
    seen_urls: set[str],
    *,
    title: str,
    snippet: str,
    url: str,
    limit: int,
) -> None:
    clean_title = title.strip()
    clean_snippet = snippet.strip()
    clean_url = url.strip()
    if (
        not clean_snippet
        or not clean_url
        or clean_url in seen_urls
        or len(results) >= limit
        or clean_url.startswith("https://duckduckgo.com/c/")
        or clean_url.startswith("http://duckduckgo.com/c/")
    ):
        return

    seen_urls.add(clean_url)
    results.append(
        WebSearchResult(
            title=clean_title or clean_url,
            snippet=clean_snippet,
            url=clean_url,
        )
    )


def _collect_related_topics(
    topics: list[object],
    results: list[WebSearchResult],
    seen_urls: set[str],
    limit: int,
) -> None:
    for topic in topics:
        if len(results) >= limit or not isinstance(topic, dict):
            return

        nested_topics = topic.get("Topics")
        if isinstance(nested_topics, list):
            _collect_related_topics(nested_topics, results, seen_urls, limit)
            continue

        text = topic.get("Text")
        url = topic.get("FirstURL")
        if isinstance(text, str) and isinstance(url, str):
            title = text.split(" - ", 1)[0]
            _append_result(results, seen_urls, title=title, snippet=text, url=url, limit=limit)


async def search_web(query: str, max_results: int = WEB_SEARCH_RESULTS_LIMIT) -> list[WebSearchResult]:
    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0"},
    ) as client:
        response = await client.get(
            DUCKDUCKGO_API_URL,
            params={
                "q": query,
                "format": "json",
                "no_html": "1",
                "no_redirect": "1",
            },
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            return []

    results: list[WebSearchResult] = []
    seen_urls: set[str] = set()
    limit = max(1, max_results)

    abstract = payload.get("AbstractText")
    abstract_url = payload.get("AbstractURL")
    heading = payload.get("Heading")
    if isinstance(abstract, str) and isinstance(abstract_url, str):
        _append_result(
            results,
            seen_urls,
            title=heading if isinstance(heading, str) else "",
            snippet=abstract,
            url=abstract_url,
            limit=limit,
        )

    definition = payload.get("Definition")
    definition_url = payload.get("DefinitionURL")
    if isinstance(definition, str) and isinstance(definition_url, str):
        _append_result(
            results,
            seen_urls,
            title="Definition",
            snippet=definition,
            url=definition_url,
            limit=limit,
        )

    related_topics = payload.get("RelatedTopics")
    if isinstance(related_topics, list):
        _collect_related_topics(related_topics, results, seen_urls, limit)

    return results


def format_web_context(results: list[WebSearchResult]) -> str:
    if not results:
        return ""

    lines: list[str] = []
    for index, result in enumerate(results, start=1):
        lines.append(f"{index}. {result.title}")
        lines.append(f"   Snippet: {result.snippet}")
        lines.append(f"   Source: {result.url}")
    return "\n".join(lines)
