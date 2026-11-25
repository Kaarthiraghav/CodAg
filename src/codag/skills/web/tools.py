"""Web search and page fetching with safety bounds, anti-injection delimiting, and untrusted tagging."""

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from typing import Any
from urllib.parse import urlparse
import httpx
import trafilatura

from codag.core.types import RiskTier, ToolResult
from codag.skills.base import tool
from codag.skills.registry import default_registry


class SearchProvider(ABC):
    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        """Return list of dicts with keys: title, url, snippet."""


class DuckDuckGoSearchProvider(SearchProvider):
    @staticmethod
    def _shorten_query(query: str, max_terms: int = 6) -> str:
        terms = [t for t in re.findall(r"[A-Za-z0-9._-]+", query) if t.lower() not in _STOPWORDS]
        return " ".join(terms[:max_terms]) if terms else " ".join(query.split()[:max_terms])

    def search(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
                if not results and len(query.split()) > 5:
                    short_q = self._shorten_query(query, max_terms=6)
                    if short_q and short_q.lower() != query.lower():
                        results = list(ddgs.text(short_q, max_results=max_results))
                if not results and len(query.split()) > 3:
                    shorter_q = self._shorten_query(query, max_terms=4)
                    if shorter_q and shorter_q.lower() != query.lower():
                        results = list(ddgs.text(shorter_q, max_results=max_results))
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", "") or r.get("link", ""),
                    "snippet": r.get("body", ""),
                }
                for r in results
            ]
        except Exception:
            return []


class WebEnvironment:
    def __init__(self, provider: SearchProvider | None = None, fetch_max_bytes: int = 2_000_000) -> None:
        self.provider = provider or DuckDuckGoSearchProvider()
        self.fetch_max_bytes = fetch_max_bytes


_web_env = WebEnvironment()


def configure_web(provider: SearchProvider | None = None, fetch_max_bytes: int = 2_000_000) -> None:
    global _web_env
    _web_env = WebEnvironment(provider, fetch_max_bytes)


@tool(
    name="web.search",
    tier=RiskTier.READ,
    description="Search the web for current information, returning titles, snippets, and source URLs.",
)
def search(query: str, max_results: int = 5) -> ToolResult:
    try:
        results = _web_env.provider.search(query, max_results=max_results)
        if not results:
            return ToolResult(
                call_id="",
                ok=True,
                content=f"No results found online for {query!r}.",
                untrusted=True,
            )

        lines = [f"<untrusted source=\"duckduckgo_search\" query=\"{query}\">"]
        for i, r in enumerate(results, start=1):
            lines.append(f"{i}. {r['title']}\n   URL: {r['url']}\n   Snippet: {r['snippet']}\n")
        lines.append("</untrusted>")

        return ToolResult(
            call_id="",
            ok=True,
            content="\n".join(lines),
            untrusted=True,
        )
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Search failed: {exc}", untrusted=True)


_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "did", "do", "does",
    "for", "from", "has", "have", "how", "in", "is", "it", "of", "on", "or",
    "that", "the", "this", "to", "was", "what", "when", "where", "which", "who",
    "why", "will", "with",
})


def _fetch_clean_text(url: str, timeout: float = 15.0) -> str:
    """Fetch an HTTP/HTTPS URL and extract readable text via trafilatura."""
    clean_url = url.strip()
    if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
        raise ValueError(f"Forbidden URL scheme: {clean_url!r}. Only HTTP/HTTPS URLs are allowed.")

    headers = {"User-Agent": "CodAg/0.2 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    with httpx.Client(
        headers=headers,
        timeout=timeout,
        follow_redirects=True,
        max_redirects=5,
    ) as client:
        resp = client.get(clean_url)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "").lower()
        if not any(t in content_type for t in ("text/html", "text/plain", "application/json", "application/xml")):
            raise ValueError(f"Unsupported content type {content_type!r}. Only readable web text is supported.")

        raw_bytes = resp.content
        if len(raw_bytes) > _web_env.fetch_max_bytes:
            raw_bytes = raw_bytes[: _web_env.fetch_max_bytes]

    decoded = raw_bytes.decode("utf-8", errors="replace")
    extracted = trafilatura.extract(
        decoded,
        url=clean_url,
        include_links=True,
        include_comments=False,
    )
    return extracted or getattr(resp, "text", "") or decoded


def _extract_relevant_passages(text: str, query: str, max_chars: int = 1600) -> str:
    """Rank and extract the most query-relevant passages from scraped page text."""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text.strip()

    terms = [
        t for t in re.findall(r"[a-z0-9]{2,}", query.lower())
        if t not in _STOPWORDS
    ]
    paragraphs = [p.strip() for p in re.split(r"\n+", text) if len(p.strip()) >= 30]
    if not paragraphs:
        return text[:max_chars].strip()

    scored: list[tuple[int, int, str]] = []
    for idx, para in enumerate(paragraphs):
        lower_p = para.lower()
        unique_hits = sum(1 for t in set(terms) if t in lower_p)
        total_hits = sum(lower_p.count(t) for t in terms)
        score = unique_hits * 3 + total_hits
        scored.append((score, idx, para))

    # Select highest-scoring paragraphs up to max_chars, then restore document order
    scored.sort(key=lambda item: (-item[0], item[1]))
    chosen: list[tuple[int, str]] = []
    used_chars = 0
    for score, idx, para in scored:
        if used_chars + len(para) + 2 > max_chars:
            if not chosen:
                chosen.append((idx, para[:max_chars]))
            continue
        chosen.append((idx, para))
        used_chars += len(para) + 2

    chosen.sort(key=lambda item: item[0])
    return "\n\n".join(p for _, p in chosen)


@tool(
    name="web.fetch_page",
    tier=RiskTier.READ,
    description="Fetch and extract readable text from an HTTP/HTTPS URL with size limits and citations.",
)
def fetch_page(url: str, max_chars: int = 6000) -> ToolResult:
    clean_url = url.strip()
    try:
        text_content = _fetch_clean_text(clean_url, timeout=15.0)
        truncated = False
        if len(text_content) > max_chars:
            text_content = text_content[:max_chars]
            truncated = True

        out = f"<untrusted source=\"{clean_url}\">\n{text_content}\n"
        if truncated:
            out += f"... [Truncated to {max_chars} chars]\n"
        out += "</untrusted>"

        return ToolResult(
            call_id="",
            ok=True,
            content=out,
            untrusted=True,
        )
    except ValueError as exc:
        return ToolResult(call_id="", ok=False, content=str(exc), untrusted=True)
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to fetch {clean_url}: {exc}", untrusted=True)


@tool(
    name="web.research_and_verify",
    tier=RiskTier.READ,
    description="Search the web, scrape multiple independent sources, and extract ranked evidence passages with URLs for cross-checked answers.",
)
def research_and_verify(query: str, num_sources: int = 4) -> ToolResult:
    """Search, scrape multiple independent domains, and extract high-signal passages for grounded verification."""
    target_count = max(1, min(int(num_sources), 6))
    try:
        candidates = _web_env.provider.search(query, max_results=max(target_count * 2, 8))
        if not candidates:
            return ToolResult(
                call_id="",
                ok=True,
                content=f"No online sources found for {query!r}. Do not guess or fabricate facts.",
                untrusted=True,
            )

        # Deduplicate by domain so we cross-check independent sources
        unique_candidates: list[dict[str, str]] = []
        seen_domains: set[str] = set()
        for item in candidates:
            url = item.get("url", "").strip()
            if not (url.startswith("http://") or url.startswith("https://")):
                continue
            domain = urlparse(url).netloc.lower().removeprefix("www.")
            if domain and domain not in seen_domains:
                seen_domains.add(domain)
                unique_candidates.append({**item, "domain": domain})

        if not unique_candidates:
            unique_candidates = [c for c in candidates if c.get("url", "").startswith(("http://", "https://"))]

        to_fetch = unique_candidates[: target_count + 2]
        scraped: list[dict[str, str]] = []

        def _scrape_one(cand: dict[str, str]) -> dict[str, str] | None:
            try:
                raw_text = _fetch_clean_text(cand["url"], timeout=10.0)
                passages = _extract_relevant_passages(raw_text, query, max_chars=1500)
                if not passages:
                    return None
                return {
                    "title": cand.get("title", "Untitled"),
                    "url": cand["url"],
                    "domain": cand.get("domain", urlparse(cand["url"]).netloc),
                    "evidence": passages,
                }
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=min(4, len(to_fetch))) as pool:
            futures = {pool.submit(_scrape_one, cand): idx for idx, cand in enumerate(to_fetch)}
            ordered_results: dict[int, dict[str, str]] = {}
            for fut in as_completed(futures):
                idx = futures[fut]
                res = fut.result()
                if res:
                    ordered_results[idx] = res

        for idx in sorted(ordered_results):
            scraped.append(ordered_results[idx])
            if len(scraped) >= target_count:
                break

        # Fallback to search snippets if all page scrapes failed (e.g. bot-blocked sites)
        if not scraped:
            lines = [f"<untrusted source=\"web_search_snippets_only\" query=\"{query}\">"]
            lines.append("Note: Full page scraping was blocked; only search snippets are available.")
            for i, c in enumerate(unique_candidates[:target_count], start=1):
                lines.append(f"[{i}] {c.get('title', 'Untitled')}\nURL: {c['url']}\nSnippet: {c.get('snippet', '')}\n")
            lines.append("</untrusted>")
            return ToolResult(call_id="", ok=True, content="\n".join(lines), untrusted=True)

        lines = [
            f"<untrusted source=\"multi_source_web_research\" query=\"{query}\" sources_scraped=\"{len(scraped)}\">",
            f"Scraped {len(scraped)} independent sources. Cross-check claims across them, cite [1]..[{len(scraped)}], and flag any conflicts or gaps.",
            "",
        ]
        for i, src in enumerate(scraped, start=1):
            lines.append(f"[{i}] {src['title']} ({src['domain']})")
            lines.append(f"URL: {src['url']}")
            lines.append(f"Evidence:\n{src['evidence']}\n")
        lines.append("</untrusted>")

        return ToolResult(
            call_id="",
            ok=True,
            content="\n".join(lines),
            untrusted=True,
        )
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Research failed: {exc}", untrusted=True)


default_registry.register(search)
default_registry.register(fetch_page)
default_registry.register(research_and_verify)
