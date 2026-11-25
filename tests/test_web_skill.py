from unittest.mock import MagicMock, patch
from codag.skills.web.tools import (
    SearchProvider,
    configure_web,
    fetch_page,
    research_and_verify,
    search,
)


class MockSearchProvider(SearchProvider):
    def search(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        return [
            {
                "title": "Python Official Documentation",
                "url": "https://docs.python.org/3/",
                "snippet": "Python is a programming language...",
            }
        ]


def test_web_search():
    configure_web(provider=MockSearchProvider())
    res = search("python docs")

    assert res.ok is True
    assert res.untrusted is True
    assert "https://docs.python.org/3/" in res.content
    assert "<untrusted source=" in res.content


def test_fetch_page_scheme_validation():
    # Only HTTP / HTTPS allowed
    res1 = fetch_page("file:///etc/passwd")
    assert res1.ok is False
    assert "Forbidden URL scheme" in res1.content

    res2 = fetch_page("ftp://ftp.example.com/file.zip")
    assert res2.ok is False
    assert "Forbidden URL scheme" in res2.content


def test_fetch_page_with_mock_http():
    mock_resp = MagicMock()
    mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
    mock_resp.content = b"<html><body><h1>Hello World</h1><p>Article body content.</p></body></html>"
    mock_resp.text = "Hello World Article body content."

    with patch("httpx.Client.get", return_value=mock_resp):
        res = fetch_page("https://example.com/test")
        assert res.ok is True
        assert res.untrusted is True
        assert "<untrusted source=\"https://example.com/test\">" in res.content
        assert "</untrusted>" in res.content


class MultiSourceMockProvider(SearchProvider):
    def search(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        return [
            {
                "title": "Apple M4 Specs - Apple",
                "url": "https://apple.com/mac-mini/specs",
                "snippet": "M4 chip features 10-core CPU and 16-core Neural Engine.",
            },
            {
                "title": "Apple M4 Duplicate Domain",
                "url": "https://www.apple.com/newsroom/m4",
                "snippet": "Duplicate apple.com domain should be skipped for diversity.",
            },
            {
                "title": "M4 Architecture Review - AnandTech",
                "url": "https://anandtech.com/m4-review",
                "snippet": "Independent review of M4 unified memory bandwidth.",
            },
        ]


def test_research_and_verify_multi_source():
    configure_web(provider=MultiSourceMockProvider())

    def fake_get(self, url, **kwargs):
        resp = MagicMock()
        resp.headers = {"content-type": "text/html; charset=utf-8"}
        if "apple.com" in url:
            body = "Apple M4 chip has a 10-core CPU, 10-core GPU, and 16-core Neural Engine with 120GB/s memory bandwidth."
        else:
            body = "Our benchmarks confirm the Apple M4 16-core Neural Engine delivers 38 TOPS and 120GB/s unified memory."
        resp.content = f"<html><body><p>{body}</p></body></html>".encode("utf-8")
        resp.text = body
        return resp

    with patch("httpx.Client.get", new=fake_get):
        res = research_and_verify("Apple M4 Neural Engine specs", num_sources=3)
        assert res.ok is True
        assert res.untrusted is True
        assert "multi_source_web_research" in res.content
        assert "sources_scraped=\"2\"" in res.content
        assert "[1] Apple M4 Specs - Apple (apple.com)" in res.content
        assert "[2] M4 Architecture Review - AnandTech (anandtech.com)" in res.content
        assert "16-core Neural Engine" in res.content
        assert "38 TOPS" in res.content


def test_research_and_verify_snippet_fallback():
    configure_web(provider=MultiSourceMockProvider())
    with patch("httpx.Client.get", side_effect=RuntimeError("Blocked")):
        res = research_and_verify("Apple M4 specs", num_sources=2)
        assert res.ok is True
        assert res.untrusted is True
        assert "web_search_snippets_only" in res.content
        assert "https://apple.com/mac-mini/specs" in res.content
