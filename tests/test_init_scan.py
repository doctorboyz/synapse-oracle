"""Tests for init scan — helpers + integration (updated detection, supersede flow)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ingest.init_scan import (
    SCAN_EXTENSIONS,
    should_skip,
    scan_files,
    read_text_file,
    read_file_content,
    init_scan,
)


class TestShouldSkip:
    def test_should_skip_hidden_directory(self):
        path = Path("/project/.git/config")
        assert should_skip(path) is True

    def test_should_skip_hidden_file(self):
        path = Path("/project/.env")
        assert should_skip(path) is True

    def test_should_skip_node_modules(self):
        path = Path("/project/node_modules/lodash/index.js")
        assert should_skip(path) is True

    def test_should_skip_pycache(self):
        path = Path("/project/__pycache__/foo.cpython-312.pyc")
        assert should_skip(path) is True

    def test_should_skip_venv(self):
        path = Path("/project/venv/bin/python")
        assert should_skip(path) is True

    def test_should_not_skip_normal_file(self):
        path = Path("/project/src/main.py")
        assert should_skip(path) is False

    def test_should_not_skip_markdown(self):
        path = Path("/project/docs/readme.md")
        assert should_skip(path) is False

    def test_should_skip_tox_directory(self):
        path = Path("/project/.tox/py312/bin/python")
        assert should_skip(path) is True


class TestScanFiles:
    def test_scan_files_finds_text_files(self, tmp_path):
        # Create some files
        (tmp_path / "readme.md").write_text("# Hello")
        (tmp_path / "notes.txt").write_text("notes")
        (tmp_path / "script.py").write_text("print('hello')")

        files = scan_files(tmp_path)
        assert len(files) == 2
        assert all(f.suffix in {".md", ".txt"} for f in files)

    def test_scan_files_skips_hidden_directories(self, tmp_path):
        hidden_dir = tmp_path / ".hidden"
        hidden_dir.mkdir()
        (hidden_dir / "secret.md").write_text("secret")
        (tmp_path / "visible.md").write_text("visible")

        files = scan_files(tmp_path)
        assert len(files) == 1
        assert files[0].name == "visible.md"

    def test_scan_files_skips_skip_dirs(self, tmp_path):
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        (venv_dir / "notes.md").write_text("in venv")
        (tmp_path / "real.md").write_text("real")

        files = scan_files(tmp_path)
        assert len(files) == 1
        assert files[0].name == "real.md"

    def test_scan_files_walks_subdirectories(self, tmp_path):
        sub = tmp_path / "docs" / "guide"
        sub.mkdir(parents=True)
        (sub / "intro.md").write_text("intro")
        (sub / "advanced.rst").write_text("advanced")

        files = scan_files(tmp_path)
        assert len(files) == 2
        names = {f.name for f in files}
        assert names == {"intro.md", "advanced.rst"}

    def test_scan_files_case_insensitive_extensions(self, tmp_path):
        (tmp_path / "readme.MD").write_text("# Hello")
        (tmp_path / "notes.TXT").write_text("notes")

        files = scan_files(tmp_path)
        assert len(files) == 2

    def test_scan_files_returns_sorted(self, tmp_path):
        (tmp_path / "z.md").write_text("z")
        (tmp_path / "a.md").write_text("a")
        (tmp_path / "m.md").write_text("m")

        files = scan_files(tmp_path)
        names = [f.name for f in files]
        assert names == ["a.md", "m.md", "z.md"]

    def test_scan_files_empty_directory(self, tmp_path):
        files = scan_files(tmp_path)
        assert files == []

    def test_scan_files_skips_files_in_skip_dirs(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "COMMIT_EDITMSG").write_text("commit")
        (tmp_path / "main.txt").write_text("main")

        files = scan_files(tmp_path)
        assert len(files) == 1
        assert files[0].name == "main.txt"


class TestReadTextFile:
    def test_read_text_file_reads_utf8(self, tmp_path):
        fpath = tmp_path / "test.txt"
        fpath.write_text("hello world", encoding="utf-8")
        result = read_text_file(fpath)
        assert result == "hello world"

    def test_read_text_file_reads_unicode(self, tmp_path):
        fpath = tmp_path / "test.txt"
        fpath.write_text("Hello 世界 🌍", encoding="utf-8")
        result = read_text_file(fpath)
        assert result == "Hello 世界 🌍"

    def test_read_text_file_returns_none_on_missing_file(self, tmp_path):
        fpath = tmp_path / "missing.txt"
        result = read_text_file(fpath)
        assert result is None

    def test_read_text_file_returns_none_on_binary_file(self, tmp_path):
        fpath = tmp_path / "binary.bin"
        fpath.write_bytes(b"\x89PNG\r\n\x1a\n")
        result = read_text_file(fpath)
        assert result is None


class TestReadFileContent:
    def test_read_file_content_text_file(self, tmp_path):
        fpath = tmp_path / "notes.md"
        fpath.write_text("# Notes", encoding="utf-8")
        result = read_file_content(fpath)
        assert result == "# Notes"

    def test_read_file_content_txt_file(self, tmp_path):
        fpath = tmp_path / "log.txt"
        fpath.write_text("log entry", encoding="utf-8")
        result = read_file_content(fpath)
        assert result == "log entry"

    def test_read_file_content_rst_file(self, tmp_path):
        fpath = tmp_path / "doc.rst"
        fpath.write_text("Title\n=====")
        result = read_file_content(fpath)
        assert result == "Title\n====="

    def test_read_file_content_unsupported_extension_returns_none(self, tmp_path):
        fpath = tmp_path / "image.png"
        fpath.write_bytes(b"\x89PNG")
        result = read_file_content(fpath)
        assert result is None

    def test_read_file_content_pdf_with_mock(self, tmp_path):
        fpath = tmp_path / "doc.pdf"
        fpath.write_bytes(b"%PDF-1.4")

        mock_pdf_module = type(sys)("pypdf")
        MockReader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "PDF content"
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        MockReader.return_value = mock_reader
        mock_pdf_module.PdfReader = MockReader

        with patch.dict(sys.modules, {"pypdf": mock_pdf_module}):
            result = read_file_content(fpath)
            assert result == "PDF content"
            MockReader.assert_called_once_with(str(fpath))

    def test_read_file_content_pdf_import_error_returns_none(self, tmp_path):
        fpath = tmp_path / "doc.pdf"
        fpath.write_bytes(b"%PDF-1.4")

        with patch("src.ingest.init_scan.read_pdf_file", return_value=None) as mock_read_pdf:
            result = read_file_content(fpath)
            assert result is None
            mock_read_pdf.assert_called_once_with(fpath)

    def test_read_file_content_docx_with_mock(self, tmp_path):
        fpath = tmp_path / "doc.docx"
        fpath.write_bytes(b"PK\x03\x04")  # DOCX is a zip file

        mock_docx_module = type(sys)("docx")
        MockDocument = MagicMock()
        mock_para = MagicMock()
        mock_para.text = "  Hello  "
        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_para]
        MockDocument.return_value = mock_doc
        mock_docx_module.Document = MockDocument

        with patch.dict(sys.modules, {"docx": mock_docx_module}):
            result = read_file_content(fpath)
            assert result == "  Hello  "
            MockDocument.assert_called_once_with(str(fpath))

    def test_read_file_content_docx_import_error_returns_none(self, tmp_path):
        fpath = tmp_path / "doc.docx"
        fpath.write_bytes(b"PK\x03\x04")

        with patch("src.ingest.init_scan.read_docx_file", return_value=None) as mock_read_docx:
            result = read_file_content(fpath)
            assert result is None
            mock_read_docx.assert_called_once_with(fpath)


@pytest.mark.asyncio
class TestInitScanIntegration:
    """Integration tests for init_scan() — updated file detection, supersede, skip unchanged."""

    async def test_init_scan_basic(self, clean_pg, tmp_path, monkeypatch):
        """Scan a directory with markdown files, verify they get indexed."""
        from src.config import Settings

        (tmp_path / "readme.md").write_text("# Project\n\nA sample project description")
        (tmp_path / "notes.txt").write_text("TODO: refactor the auth module")

        monkeypatch.setenv("DATABASE_URL", clean_pg._settings.database_url)

        result = await init_scan(str(tmp_path), tags=["test-project"])
        assert result["total_files"] == 2
        assert result["indexed"] == 2
        assert result["errors"] == 0

    async def test_init_scan_skips_unchanged(self, clean_pg, tmp_path, monkeypatch):
        """Second scan of unchanged files should skip them with skipped_unchanged."""
        from src.config import Settings

        (tmp_path / "notes.md").write_text("original content for testing")
        monkeypatch.setenv("DATABASE_URL", clean_pg._settings.database_url)

        r1 = await init_scan(str(tmp_path), tags=["test-project"])
        assert r1["indexed"] == 1

        r2 = await init_scan(str(tmp_path), tags=["test-project"])
        assert r2["total_files"] == 1
        assert r2["skipped_unchanged"] == 1
        assert r2["indexed"] == 0

    async def test_init_scan_supersedes_updated(self, clean_pg, tmp_path, monkeypatch):
        """Modified file should trigger supersede + re-index (not new index)."""
        from src.config import Settings

        note = tmp_path / "changelog.md"
        note.write_text("version 1: initial release")
        monkeypatch.setenv("DATABASE_URL", clean_pg._settings.database_url)

        r1 = await init_scan(str(tmp_path), tags=["test-project"])
        assert r1["indexed"] == 1

        note.write_text("version 2: added new features and bug fixes")
        r2 = await init_scan(str(tmp_path), tags=["test-project"])
        assert r2["superseded"] >= 1
        assert r2["skipped_unchanged"] == 0

    async def test_init_scan_dry_run(self, clean_pg, tmp_path, monkeypatch):
        """Dry run should not write to database."""
        from src.config import Settings

        (tmp_path / "dry.md").write_text("dry run content")
        monkeypatch.setenv("DATABASE_URL", clean_pg._settings.database_url)

        result = await init_scan(str(tmp_path), tags=["test"], dry_run=True)
        assert result["total_files"] == 1
        assert result["indexed"] == 0
        assert len(result["files"]) == 1
        assert result["files"][0]["status"] == "dry_run"

    async def test_init_scan_empty_file(self, clean_pg, tmp_path, monkeypatch):
        """Empty files should be skipped, not errored."""
        from src.config import Settings

        (tmp_path / "empty.md").write_text("")
        monkeypatch.setenv("DATABASE_URL", clean_pg._settings.database_url)

        result = await init_scan(str(tmp_path), tags=["test"])
        assert result["total_files"] == 1
        assert result["indexed"] == 0

    async def test_init_scan_nonexistent_path(self):
        result = await init_scan("/nonexistent/path/xyz")
        assert "error" in result

    async def test_init_scan_not_a_directory(self, tmp_path):
        f = tmp_path / "file.md"
        f.write_text("content")
        result = await init_scan(str(f))
        assert "error" in result

    async def test_init_scan_oracle_path_metadata(self, clean_pg, tmp_path, monkeypatch):
        """Files under oracle project structure get oracle metadata extracted."""
        from src.config import Settings

        psi_dir = tmp_path / "ψ" / "memory" / "learnings"
        psi_dir.mkdir(parents=True)
        (psi_dir / "pattern-001.md").write_text("Emily discovered a pattern")

        monkeypatch.setenv("DATABASE_URL", clean_pg._settings.database_url)

        result = await init_scan(str(tmp_path))
        indexed = [f for f in result["files"] if f["status"] == "indexed"]
        assert len(indexed) >= 1
