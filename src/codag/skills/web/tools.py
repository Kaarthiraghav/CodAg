"""Web search and page fetching with safety bounds, anti-injection delimiting, and untrusted tagging."""

from abc import ABC, abstractmethod
from typing import Any
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
    def search(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
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


@tool(
    name="web.fetch_page",
    tier=RiskTier.READ,
    description="Fetch and extract readable text from an HTTP/HTTPS URL with size limits and citations.",
)
def fetch_page(url: str, max_chars: int = 6000) -> ToolResult:
    clean_url = url.strip()
    # 1. Scheme validation: HTTP/HTTPS only
    if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
        return ToolResult(
            call_id="",
            ok=False,
            content=f"Forbidden URL scheme: {clean_url!r}. Only HTTP/HTTPS URLs are allowed.",
            untrusted=True,
        )

    headers = {"User-Agent": "CodAg/0.2 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

    try:
        with httpx.Client(
            headers=headers,
            timeout=15.0,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            resp = client.get(clean_url)
            resp.raise_for_status()

            # Content-type verification
            content_type = resp.headers.get("content-type", "").lower()
            if not any(t in content_type for t in ("text/html", "text/plain", "application/json", "application/xml")):
                return ToolResult(
                    call_id="",
                    ok=False,
                    content=f"Unsupported content type {content_type!r}. Only readable web text is supported.",
                    untrusted=True,
                )

            raw_bytes = resp.content
            if len(raw_bytes) > _web_env.fetch_max_bytes:
                raw_bytes = raw_bytes[: _web_env.fetch_max_bytes]

        # Extract text using trafilatura
        extracted = trafilatura.extract(
            raw_bytes.decode("utf-8", errors="replace"),
            url=clean_url,
            include_links=True,
            include_comments=False,
        )

        text_content = extracted or resp.text[:max_chars]
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
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to fetch {clean_url}: {exc}", untrusted=True)


default_registry.register(search)
default_registry.register(fetch_page)
