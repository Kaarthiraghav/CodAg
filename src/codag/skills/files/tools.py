"""File operations tools for CodAg."""

import fnmatch
from pathlib import Path

from codag.core.types import RiskTier, ToolResult
from codag.safety.sandbox import Sandbox, SandboxError
from codag.safety.snapshots import SnapshotManager
from codag.skills.base import tool
from codag.skills.registry import default_registry


class FileTools:
    def __init__(
        self,
        sandbox: Sandbox | None = None,
        snapshots: SnapshotManager | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.snapshots = snapshots

    def set_environment(self, sandbox: Sandbox, snapshots: SnapshotManager) -> None:
        self.sandbox = sandbox
        self.snapshots = snapshots


# Global instance for tool handlers
_file_tools_instance = FileTools()


def configure_file_tools(sandbox: Sandbox, snapshots: SnapshotManager) -> None:
    _file_tools_instance.set_environment(sandbox, snapshots)


@tool(
    name="files.list_directory",
    tier=RiskTier.READ,
    description="List files and subdirectories in an allowed directory.",
)
def list_directory(path: str = ".", max_items: int = 100) -> ToolResult:
    if not _file_tools_instance.sandbox:
        return ToolResult(call_id="", ok=False, content="Sandbox not configured.")
    try:
        resolved = _file_tools_instance.sandbox.check_read(path)
        if not resolved.is_dir():
            return ToolResult(call_id="", ok=False, content=f"Not a directory: {path}")

        entries = sorted(resolved.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        lines = []
        for p in entries[:max_items]:
            kind = "dir" if p.is_dir() else "file"
            size_str = f" ({p.stat().st_size} bytes)" if p.is_file() else ""
            lines.append(f"[{kind}] {p.name}{size_str}")

        content = "\n".join(lines) if lines else "(empty directory)"
        if len(entries) > max_items:
            content += f"\n... ({len(entries) - max_items} more items truncated)"
        return ToolResult(call_id="", ok=True, content=content)
    except SandboxError as exc:
        return ToolResult(call_id="", ok=False, content=str(exc))
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Error listing directory: {exc}")


def _extract_pdf_text(path: Path, max_chars: int = 8000) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages_text = []
        chars_count = 0
        for i, page in enumerate(reader.pages):
            txt = page.extract_text() or ""
            if txt:
                pages_text.append(f"--- Page {i+1} ---\n{txt.strip()}")
                chars_count += len(txt)
                if chars_count >= max_chars:
                    break
        return "\n\n".join(pages_text) if pages_text else "(No text extracted from PDF)"
    except Exception as exc:
        return f"Error reading PDF: {exc}"


def _extract_pptx_text(path: Path, max_chars: int = 8000) -> str:
    import zipfile
    import xml.etree.ElementTree as ET
    try:
        texts = []
        chars_count = 0
        with zipfile.ZipFile(str(path)) as z:
            slide_files = sorted([f for f in z.namelist() if f.startswith("ppt/slides/slide") and f.endswith(".xml")])
            for i, sf in enumerate(slide_files):
                tree = ET.fromstring(z.read(sf))
                slide_words = []
                for elem in tree.iter():
                    if elem.tag.endswith("}t") and elem.text:
                        slide_words.append(elem.text)
                if slide_words:
                    slide_text = f"--- Slide {i+1} ---\n" + " ".join(slide_words)
                    texts.append(slide_text)
                    chars_count += len(slide_text)
                    if chars_count >= max_chars:
                        break
        return "\n\n".join(texts) if texts else "(No text extracted from presentation)"
    except Exception as exc:
        return f"Error reading presentation: {exc}"


@tool(
    name="files.read_file",
    tier=RiskTier.READ,
    description="Read text contents of a file (supports plain text, markdown, PDF, and PPTX).",
)
def read_file(path: str, max_chars: int = 8000) -> ToolResult:
    if not _file_tools_instance.sandbox:
        return ToolResult(call_id="", ok=False, content="Sandbox not configured.")
    try:
        resolved = _file_tools_instance.sandbox.check_read(path)
        if not resolved.is_file():
            return ToolResult(call_id="", ok=False, content=f"Not a file: {path}")

        # Taint tracking check: if reading from outside workspace roots, mark untrusted
        in_workspace = _file_tools_instance.sandbox.is_in_workspace(resolved)
        untrusted = not in_workspace

        ext = resolved.suffix.lower()
        if ext == ".pdf":
            text = _extract_pdf_text(resolved, max_chars)
        elif ext in {".pptx", ".ppt"}:
            text = _extract_pptx_text(resolved, max_chars)
        else:
            text = resolved.read_text(encoding="utf-8", errors="replace")

        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars]
            truncated = True

        out = text
        if truncated:
            out += f"\n... [Truncated: showing first {max_chars} characters]"
        return ToolResult(call_id="", ok=True, content=out, untrusted=untrusted)
    except SandboxError as exc:
        return ToolResult(call_id="", ok=False, content=str(exc))
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Error reading file: {exc}")


@tool(
    name="files.search_files",
    tier=RiskTier.READ,
    description="Search for files matching a glob pattern in an allowed folder.",
)
def search_files(pattern: str, path: str = ".", max_results: int = 50) -> ToolResult:
    if not _file_tools_instance.sandbox:
        return ToolResult(call_id="", ok=False, content="Sandbox not configured.")
    try:
        resolved = _file_tools_instance.sandbox.check_read(path)
        if not resolved.is_dir():
            return ToolResult(call_id="", ok=False, content=f"Not a directory: {path}")

        matches: list[str] = []
        for p in resolved.rglob("*"):
            if _file_tools_instance.sandbox.is_denied(p):
                continue
            if fnmatch.fnmatch(p.name, pattern):
                try:
                    rel = p.relative_to(resolved)
                    matches.append(str(rel))
                    if len(matches) >= max_results:
                        break
                except ValueError:
                    matches.append(str(p))

        content = "\n".join(matches) if matches else f"No files matching pattern {pattern!r} found."
        return ToolResult(call_id="", ok=True, content=content)
    except SandboxError as exc:
        return ToolResult(call_id="", ok=False, content=str(exc))
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Error searching files: {exc}")


@tool(
    name="files.create_file",
    tier=RiskTier.SAFE_WRITE,
    description="Create a new file or overwrite an existing file with the provided content.",
)
def create_file(path: str, content: str) -> ToolResult:
    if not _file_tools_instance.sandbox or not _file_tools_instance.snapshots:
        return ToolResult(call_id="", ok=False, content="Environment not configured.")
    try:
        resolved, _ = _file_tools_instance.sandbox.check_write(path)
        # Snapshot before write (handles overwrite or undo of new file)
        undo_token = _file_tools_instance.snapshots.snapshot_before_modify(resolved)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return ToolResult(
            call_id="",
            ok=True,
            content=f"Successfully created file {path} ({len(content)} chars written).",
            undo_token=undo_token,
        )
    except SandboxError as exc:
        return ToolResult(call_id="", ok=False, content=str(exc))
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Error creating file: {exc}")


@tool(
    name="files.edit_file",
    tier=RiskTier.SAFE_WRITE,
    description="Edit an existing file by replacing old_str with new_str.",
)
def edit_file(path: str, old_str: str, new_str: str) -> ToolResult:
    if not _file_tools_instance.sandbox or not _file_tools_instance.snapshots:
        return ToolResult(call_id="", ok=False, content="Environment not configured.")
    try:
        resolved, _ = _file_tools_instance.sandbox.check_write(path)
        if not resolved.is_file():
            return ToolResult(call_id="", ok=False, content=f"File not found: {path}")

        current = resolved.read_text(encoding="utf-8")
        if old_str not in current:
            return ToolResult(call_id="", ok=False, content=f"Target string not found in {path}")

        undo_token = _file_tools_instance.snapshots.snapshot_before_modify(resolved)
        updated = current.replace(old_str, new_str)
        resolved.write_text(updated, encoding="utf-8")
        return ToolResult(
            call_id="",
            ok=True,
            content=f"Successfully updated {path}.",
            undo_token=undo_token,
        )
    except SandboxError as exc:
        return ToolResult(call_id="", ok=False, content=str(exc))
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Error editing file: {exc}")


@tool(
    name="files.move_file",
    tier=RiskTier.CONFIRM,
    description="Move or rename a file from source to destination.",
)
def move_file(source: str, destination: str) -> ToolResult:
    if not _file_tools_instance.sandbox or not _file_tools_instance.snapshots:
        return ToolResult(call_id="", ok=False, content="Environment not configured.")
    try:
        src_res = _file_tools_instance.sandbox.check_read(source)
        dst_res, _ = _file_tools_instance.sandbox.check_write(destination)
        if not src_res.exists():
            return ToolResult(call_id="", ok=False, content=f"Source path not found: {source}")

        dst_res.parent.mkdir(parents=True, exist_ok=True)
        undo_token = _file_tools_instance.snapshots.record_move(src_res, dst_res)
        src_res.rename(dst_res)
        return ToolResult(
            call_id="",
            ok=True,
            content=f"Moved {source} to {destination}.",
            undo_token=undo_token,
        )
    except SandboxError as exc:
        return ToolResult(call_id="", ok=False, content=str(exc))
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Error moving file: {exc}")


@tool(
    name="files.delete_file",
    tier=RiskTier.CONFIRM,
    description="Move a file to the CodAg trash folder.",
)
def delete_file(path: str) -> ToolResult:
    if not _file_tools_instance.sandbox or not _file_tools_instance.snapshots:
        return ToolResult(call_id="", ok=False, content="Environment not configured.")
    try:
        resolved = _file_tools_instance.sandbox.check_read(path)
        if not resolved.exists():
            return ToolResult(call_id="", ok=False, content=f"Path not found: {path}")

        undo_token = _file_tools_instance.snapshots.move_to_trash(resolved)
        return ToolResult(
            call_id="",
            ok=True,
            content=f"Moved {path} to trash.",
            undo_token=undo_token,
        )
    except SandboxError as exc:
        return ToolResult(call_id="", ok=False, content=str(exc))
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Error deleting file: {exc}")


@tool(
    name="files.allow_directory",
    tier=RiskTier.READ,
    description="Grant read access to a specific directory or external storage volume requested by the user.",
)
def allow_directory(path: str) -> ToolResult:
    if not _file_tools_instance.sandbox:
        return ToolResult(call_id="", ok=False, content="Environment not configured.")
    try:
        resolved = _file_tools_instance.sandbox.add_read_root(path)
        return ToolResult(
            call_id="",
            ok=True,
            content=f"Directory '{resolved}' has been added to allowed read roots.",
        )
    except SandboxError as exc:
        return ToolResult(call_id="", ok=False, content=str(exc))
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Error allowing directory: {exc}")


def generate_pdf_from_markdown(pdf_path: Path, title: str, content: str) -> None:
    """Render markdown-formatted notes into a styled PDF with headers, bullets, and page numbers."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.pdfgen import canvas
    import re

    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            num_pages = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self.draw_page_number(num_pages)
                super().showPage()
            super().save()

        def draw_page_number(self, page_count):
            self.saveState()
            self.setFont("Helvetica", 9)
            self.setFillColor(colors.HexColor("#64748b"))
            page_text = f"Page {self._pageNumber} of {page_count}"
            self.drawRightString(letter[0] - 54, 36, page_text)
            self.drawString(54, 36, "CodAg Notes")
            self.setStrokeColor(colors.HexColor("#e2e8f0"))
            self.setLineWidth(0.5)
            self.line(54, 48, letter[0] - 54, 48)
            self.restoreState()

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=64,
    )

    base_styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        parent=base_styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0f172a"),
        alignment=0,
        spaceAfter=10,
    )

    h1_style = ParagraphStyle(
        "DocH1",
        parent=base_styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#0284c7"),
        spaceBefore=14,
        spaceAfter=5,
        keepWithNext=True,
    )

    h2_style = ParagraphStyle(
        "DocH2",
        parent=base_styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11.5,
        leading=15,
        textColor=colors.HexColor("#0369a1"),
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True,
    )

    body_style = ParagraphStyle(
        "DocBody",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14.5,
        textColor=colors.HexColor("#334155"),
        spaceAfter=5,
    )

    bullet_style = ParagraphStyle(
        "DocBullet",
        parent=body_style,
        leftIndent=16,
        firstLineIndent=-10,
        spaceAfter=4,
    )

    story = []
    if title:
        story.append(Paragraph(title, title_style))
        story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#38bdf8"), spaceAfter=14))

    for line in content.splitlines():
        trimmed = line.strip()
        if not trimmed:
            story.append(Spacer(1, 6))
            continue

        fmt = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", trimmed)
        fmt = re.sub(r"\*(.*?)\*", r"<i>\1</i>", fmt)
        fmt = re.sub(r"`(.*?)`", r"<font name='Courier'>\1</font>", fmt)

        if trimmed.startswith("# "):
            story.append(Paragraph(fmt[2:], h1_style))
        elif trimmed.startswith("## "):
            story.append(Paragraph(fmt[3:], h1_style))
        elif trimmed.startswith("### "):
            story.append(Paragraph(fmt[4:], h2_style))
        elif trimmed.startswith("- ") or trimmed.startswith("* "):
            story.append(Paragraph(f"&bull; {fmt[2:]}", bullet_style))
        elif re.match(r"^\d+\.\s+", trimmed):
            num = re.match(r"^(\d+\.)\s+(.*)", fmt)
            if num:
                story.append(Paragraph(f"{num.group(1)} {num.group(2)}", bullet_style))
            else:
                story.append(Paragraph(fmt, body_style))
        else:
            story.append(Paragraph(fmt, body_style))

    doc.build(story, canvasmaker=NumberedCanvas)


@tool(
    name="files.create_pdf",
    tier=RiskTier.SAFE_WRITE,
    description="Generate and save a beautifully formatted PDF document from markdown or text notes.",
)
def create_pdf(path: str, title: str, content: str) -> ToolResult:
    if not _file_tools_instance.sandbox or not _file_tools_instance.snapshots:
        return ToolResult(call_id="", ok=False, content="Environment not configured.")
    try:
        # Guarantee .pdf extension
        pdf_path = path if path.lower().endswith(".pdf") else f"{path}.pdf"
        resolved, _ = _file_tools_instance.sandbox.check_write(pdf_path)

        undo_token = None
        if resolved.exists():
            undo_token = _file_tools_instance.snapshots.record_pre_modification(resolved)

        generate_pdf_from_markdown(resolved, title, content)
        return ToolResult(
            call_id="",
            ok=True,
            content=f"Successfully generated PDF document at '{resolved}'.\nDownload or view: /api/download?path={resolved}",
            undo_token=undo_token,
        )
    except SandboxError as exc:
        return ToolResult(call_id="", ok=False, content=str(exc))
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Error generating PDF: {exc}")


# Register tools in default registry
for t in (list_directory, read_file, search_files, create_file, edit_file, move_file, delete_file, allow_directory, create_pdf):
    default_registry.register(t)
