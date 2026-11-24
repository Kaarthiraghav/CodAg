from pathlib import Path
from codag.config import PolicyConfig
from codag.safety.sandbox import Sandbox
from codag.safety.snapshots import SnapshotManager
from codag.skills.files.tools import (
    configure_file_tools,
    create_file,
    delete_file,
    edit_file,
    list_directory,
    move_file,
    read_file,
    search_files,
)


def test_files_skill_crud(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    policy = PolicyConfig()
    policy.workspace.roots = [str(ws)]
    policy.workspace.read_roots = [str(ws)]

    sandbox = Sandbox(policy)
    snapshots = SnapshotManager(tmp_path / "data")
    configure_file_tools(sandbox, snapshots)

    # 1. Create file
    f_path = str(ws / "hello.txt")
    res = create_file(f_path, "Hello World")
    assert res.ok is True
    assert Path(f_path).read_text(encoding="utf-8") == "Hello World"

    # 2. Read file
    res = read_file(f_path)
    assert res.ok is True
    assert "Hello World" in res.content

    # 3. Edit file
    res = edit_file(f_path, "World", "Antigravity")
    assert res.ok is True
    assert Path(f_path).read_text(encoding="utf-8") == "Hello Antigravity"

    # 4. Search files
    res = search_files("*.txt", str(ws))
    assert res.ok is True
    assert "hello.txt" in res.content

    # 5. List directory
    res = list_directory(str(ws))
    assert res.ok is True
    assert "hello.txt" in res.content

    # 6. Move file
    dst_path = str(ws / "renamed.txt")
    res = move_file(f_path, dst_path)
    assert res.ok is True
    assert not Path(f_path).exists()
    assert Path(dst_path).exists()

    # 7. Delete file (moves to trash)
    res = delete_file(dst_path)
    assert res.ok is True
    assert not Path(dst_path).exists()

    # 8. Dynamic allow directory
    custom_dir = tmp_path / "custom_ext"
    custom_dir.mkdir()
    (custom_dir / "data.txt").write_text("external data")

    from codag.skills.files.tools import allow_directory
    res_allow = allow_directory(str(custom_dir))
    assert res_allow.ok is True

    res_read_ext = read_file(str(custom_dir / "data.txt"))
    assert res_read_ext.ok is True
    assert "external data" in res_read_ext.content

    # 9. Read PDF using pypdf
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    pdf_path = ws / "blank.pdf"
    with open(pdf_path, "wb") as f:
        writer.write(f)

    res_pdf = read_file(str(pdf_path))
    assert res_pdf.ok is True

    # 10. Generate PDF using create_pdf
    from codag.skills.files.tools import create_pdf
    gen_pdf_path = str(ws / "day1_notes.pdf")
    res_gen = create_pdf(
        path=gen_pdf_path,
        title="Day 1 Study Notes: Web Mining",
        content="## 1. Social Networks\n- Core component of Web 2.0\n- Communication and sharing",
    )
    assert res_gen.ok is True
    assert Path(gen_pdf_path).exists()
    assert Path(gen_pdf_path).stat().st_size > 500
    assert "/api/download?path=" in res_gen.content
