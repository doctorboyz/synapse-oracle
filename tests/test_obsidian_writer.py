"""Tests for Obsidian Writer — sanitize, frontmatter, wikilinks, write to vault."""

from pathlib import Path

import pytest

from src.ingest.obsidian_writer import (
    sanitize_filename,
    _build_frontmatter,
    _build_wikilinks,
    write_document_to_obsidian,
    write_search_results_to_obsidian,
)


class TestSanitizeFilename:
    def test_lowercase_and_dash(self):
        result = sanitize_filename("Hello World Note", "abc12345xxxx")
        assert result.startswith("hello-world-note-")
        assert result.endswith(".md")

    def test_strips_special_chars(self):
        result = sanitize_filename("What's New? (2024)", "abc12345xxxx")
        assert "'" not in result
        assert "?" not in result
        assert "(" not in result
        assert result.startswith("whats-new-2024-")

    def test_thai_characters_preserved(self):
        result = sanitize_filename("บันทึกความรู้", "abc12345xxxx")
        assert "บันทึกความรู้" in result

    def test_truncates_long_title(self):
        long_title = "A" * 200
        result = sanitize_filename(long_title, "abc12345xxxx")
        name_part = result.rsplit("-", 1)[0]
        assert len(name_part) <= 80

    def test_no_doc_id_suffix(self):
        result = sanitize_filename("Simple Note")
        assert result == "simple-note.md"
        assert "-" not in result.replace("simple-note.md", "")

    def test_doc_id_first_8_chars_in_filename(self):
        result = sanitize_filename("Note", "abcdefgh1234")
        assert "abcdefgh" in result


class TestBuildFrontmatter:
    def test_basic_frontmatter(self):
        doc = {"tags": ["python", "async"], "concepts": ["concurrency"]}
        result = _build_frontmatter(doc)
        assert "---" in result
        assert "tags:" in result
        assert "concepts:" in result
        assert "python" in result

    def test_frontmatter_skips_empty_fields(self):
        doc = {"tags": [], "concepts": None, "source": ""}
        result = _build_frontmatter(doc)
        assert "tags:" not in result
        assert "concepts:" not in result

    def test_frontmatter_includes_all_filled_fields(self):
        doc = {
            "tags": ["test"],
            "concepts": ["c1"],
            "source": "synapse",
            "synapse_doc_id": "abc-123",
            "created_at": "2026-05-26",
            "oracle_name": "test-oracle",
            "doc_type": "learning",
            "source_project": "test-project",
        }
        result = _build_frontmatter(doc)
        assert "tags: ['test']" in result
        assert "synapse_doc_id: abc-123" in result
        assert "oracle_name: test-oracle" in result
        assert "doc_type: learning" in result
        assert "source_project: test-project" in result


class TestBuildWikilinks:
    def test_basic_wikilinks(self):
        related = [
            {"id": "1", "title": "Async Python"},
            {"id": "2", "title": "Docker Tips"},
        ]
        links = _build_wikilinks(related, "3")
        assert len(links) == 2
        assert "- [[Async Python]]" in links
        assert "- [[Docker Tips]]" in links

    def test_excludes_exclude_id(self):
        related = [
            {"id": "1", "title": "Self Referential"},
            {"id": "2", "title": "Other"},
        ]
        links = _build_wikilinks(related, "1")
        assert len(links) == 1
        assert "- [[Other]]" in links

    def test_deduplicates_titles(self):
        related = [
            {"id": "1", "title": "Same Title"},
            {"id": "2", "title": "Same Title"},
        ]
        links = _build_wikilinks(related, "3")
        assert len(links) == 1

    def test_skips_empty_titles(self):
        related = [
            {"id": "1", "title": ""},
            {"id": "2", "title": "   "},
            {"id": "3", "title": "Valid"},
        ]
        links = _build_wikilinks(related, "4")
        assert len(links) == 1
        assert "- [[Valid]]" in links

    def test_skips_empty_id(self):
        related = [
            {"id": "", "title": "No ID"},
        ]
        links = _build_wikilinks(related, "1")
        assert len(links) == 1

    def test_empty_related_list(self):
        links = _build_wikilinks([], "1")
        assert links == []


@pytest.mark.asyncio
class TestWriteDocumentToObsidian:
    async def test_write_basic_document(self, clean_pg, tmp_path):
        add_result = await clean_pg.add(
            title="Test Note", content="Some content here",
            tags=["test"], concepts=["testing"],
            oracle_name="test-oracle", doc_type="learning",
            source_project="test-project",
        )
        vault = tmp_path / "obsidian-vault"
        vault.mkdir()

        result = await write_document_to_obsidian(clean_pg, add_result["id"], str(vault))

        assert "error" not in result
        assert result["title"] == "Test Note"
        assert result["doc_id"] == add_result["id"]

        written_file = vault / (result["file"].split("/")[-1])
        content = written_file.read_text()
        assert "---" in content
        assert "# Test Note" in content
        assert "Some content here" in content
        assert "## Related Notes" in content

    async def test_write_with_subdir(self, clean_pg, tmp_path):
        add_result = await clean_pg.add(
            title="Subdir Note", content="Content", tags=["test"],
        )
        vault = tmp_path / "obsidian-vault"
        vault.mkdir()

        result = await write_document_to_obsidian(
            clean_pg, add_result["id"], str(vault), subdir="imports"
        )

        assert "error" not in result
        assert "imports" in result["file"]

    async def test_write_nonexistent_document(self, clean_pg, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()

        result = await write_document_to_obsidian(
            clean_pg, "00000000-0000-0000-0000-000000000000", str(vault)
        )
        assert "error" in result

    async def test_write_with_trace_links(self, clean_pg, tmp_path):
        doc_a = await clean_pg.add(
            title="Source Note", content="Original content", tags=["test"],
        )
        doc_b = await clean_pg.add(
            title="Related Note", content="Derived from source", tags=["test"],
        )
        await clean_pg.add_trace(doc_a["id"], doc_b["id"], "derived_from")

        vault = tmp_path / "vault"
        vault.mkdir()

        result = await write_document_to_obsidian(clean_pg, doc_a["id"], str(vault))
        assert "error" not in result

        written_file = vault / (result["file"].split("/")[-1])
        content = written_file.read_text()
        assert "[[Related Note]]" in content

    async def test_frontmatter_in_output(self, clean_pg, tmp_path):
        add_result = await clean_pg.add(
            title="FM Test", content="Content",
            tags=["devops", "docker"], concepts=["container"],
            oracle_name="test", doc_type="pattern",
            source_project="my-project",
        )
        vault = tmp_path / "vault"
        vault.mkdir()

        result = await write_document_to_obsidian(clean_pg, add_result["id"], str(vault))
        written_file = vault / (result["file"].split("/")[-1])
        content = written_file.read_text()

        assert "tags:" in content
        assert "devops" in content
        assert "synapse_doc_id:" in content
        assert result["doc_id"][:8] in content
        assert "doc_type: pattern" in content
        assert "source_project: my-project" in content

    async def test_filename_collision_handling(self, clean_pg, tmp_path):
        """If a file with the same name already exists, append a counter."""
        add_result = await clean_pg.add(
            title="Collision Note", content="Content A", tags=["test"],
        )
        vault = tmp_path / "vault"
        vault.mkdir()

        # First write
        result1 = await write_document_to_obsidian(clean_pg, add_result["id"], str(vault))
        file1 = vault / (result1["file"].split("/")[-1])

        # Write again with same doc — the existing file should be detected
        # The collision avoidance appends a counter
        assert file1.exists()

        # Write second doc with same title but different doc_id -> different filename suffix
        add_result2 = await clean_pg.add(
            title="Collision Note", content="Content B", tags=["test"],
        )
        result2 = await write_document_to_obsidian(clean_pg, add_result2["id"], str(vault))
        file2 = vault / (result2["file"].split("/")[-1])

        assert file2.exists()
        assert file1 != file2

    async def test_no_traces_fallback(self, clean_pg, tmp_path):
        """Doc with no trace links should show fallback message."""
        add_result = await clean_pg.add(
            title="Isolated Note", content="No connections", tags=["test"],
        )
        vault = tmp_path / "vault"
        vault.mkdir()

        result = await write_document_to_obsidian(clean_pg, add_result["id"], str(vault))
        written_file = vault / (result["file"].split("/")[-1])
        content = written_file.read_text()
        assert "No related notes found" in content


@pytest.mark.asyncio
class TestWriteSearchResultsToObsidian:
    async def test_write_search_results(self, clean_pg, tmp_path):
        doc_a = await clean_pg.add(
            title="Search Hit A", content="Content A", tags=["test"],
        )
        doc_b = await clean_pg.add(
            title="Search Hit B", content="Content B", tags=["test"],
        )

        vault = tmp_path / "vault"
        vault.mkdir()

        docs = [{"id": doc_a["id"]}, {"id": doc_b["id"]}]
        result = await write_search_results_to_obsidian(clean_pg, docs, str(vault))

        assert result["written"] == 2
        assert len(result["files"]) == 2

        for fpath in result["files"]:
            assert Path(fpath).exists()

    async def test_write_search_results_skips_bad_ids(self, clean_pg, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()

        docs = [{"id": None}, {"id": "00000000-0000-0000-0000-000000000000"}]
        result = await write_search_results_to_obsidian(clean_pg, docs, str(vault))

        assert result["written"] == 0

    async def test_write_search_results_empty(self, clean_pg, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()

        result = await write_search_results_to_obsidian(clean_pg, [], str(vault))
        assert result["written"] == 0
        assert result["files"] == []

    async def test_write_search_results_mixed(self, clean_pg, tmp_path):
        doc_a = await clean_pg.add(
            title="Valid Doc", content="Content", tags=["test"],
        )
        vault = tmp_path / "vault"
        vault.mkdir()

        docs = [
            {"id": doc_a["id"]},
            {"id": "00000000-0000-0000-0000-000000000000"},
        ]
        result = await write_search_results_to_obsidian(clean_pg, docs, str(vault))

        assert result["written"] == 1
        assert len(result["files"]) == 1
