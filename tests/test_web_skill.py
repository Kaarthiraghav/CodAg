from unittest.mock import MagicMock, patch
from codag.skills.web.tools import (
    SearchProvider,
    configure_web,
    download_file,
    download_papers,
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


def test_duckduckgo_shorten_query_helper():
    from codag.skills.web.tools import DuckDuckGoSearchProvider

    short = DuckDuckGoSearchProvider._shorten_query(
        "what are the exact CPU GPU Neural Engine cores of Apple M4 Mac mini specifications",
        max_terms=6,
    )
    assert len(short.split()) <= 6
    assert "CPU" in short
    assert "GPU" in short


def test_download_file_pdf_and_scheme_validation(tmp_path):
    from codag.config import PolicyConfig
    from codag.safety.sandbox import Sandbox
    from codag.safety.snapshots import SnapshotManager

    policy = PolicyConfig()
    policy.workspace.roots = [str(tmp_path)]
    sandbox = Sandbox(policy)
    snapshots = SnapshotManager(tmp_path)
    configure_web(sandbox=sandbox, snapshots=snapshots)

    # Scheme validation
    bad_res = download_file("file:///etc/passwd", str(tmp_path / "out.pdf"))
    assert bad_res.ok is False
    assert "Forbidden URL scheme" in bad_res.content

    # Successful PDF download
    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    mock_resp = MagicMock()
    mock_resp.headers = {"content-type": "application/pdf"}
    mock_resp.content = pdf_bytes

    target_pdf = tmp_path / "papers" / "chess_paper.pdf"
    with patch("httpx.Client.get", return_value=mock_resp):
        res = download_file("https://arxiv.org/pdf/2401.00001.pdf", str(target_pdf))

    assert res.ok is True
    assert target_pdf.exists()
    assert target_pdf.read_bytes() == pdf_bytes


def test_download_papers_arxiv_mock(tmp_path):
    from codag.config import PolicyConfig
    from codag.safety.sandbox import Sandbox
    from codag.safety.snapshots import SnapshotManager

    policy = PolicyConfig()
    policy.workspace.roots = [str(tmp_path)]
    configure_web(sandbox=Sandbox(policy), snapshots=SnapshotManager(tmp_path))

    arxiv_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/2401.12345v1</id>
        <title>Blunder Dynamics in Speed Chess</title>
      </entry>
      <entry>
        <id>http://arxiv.org/abs/2311.54321v1</id>
        <title>Time Pressure and Decision Quality</title>
      </entry>
    </feed>"""

    def fake_get(self, url, **kwargs):
        resp = MagicMock()
        if "export.arxiv.org" in url:
            resp.text = arxiv_xml
        elif "arxiv.org/pdf/" in url:
            resp.content = b"%PDF-1.5\n%mock pdf"
        else:
            resp.json.return_value = {"results": []}
        return resp

    out_dir = tmp_path / "papers"
    with patch("httpx.Client.get", new=fake_get):
        res = download_papers("speed chess blunders", str(out_dir), max_papers=2)

    assert res.ok is True
    assert "Downloaded 2 PDF papers" in res.content
    assert (out_dir / "Blunder_Dynamics_in_Speed_Chess.pdf").exists()
    assert (out_dir / "Time_Pressure_and_Decision_Quality.pdf").exists()
