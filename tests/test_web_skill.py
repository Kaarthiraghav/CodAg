from unittest.mock import MagicMock, patch
from codag.skills.web.tools import (
    SearchProvider,
    configure_web,
    fetch_page,
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
