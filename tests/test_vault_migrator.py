"""Tests for vault_migrator — scan_memory_files and migrate."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.migrate import vault_migrator as migrator_mod
from src.migrate.vault_migrator import scan_memory_files, migrate


class TestScanMemoryFiles:
    def test_no_memory_root_returns_empty(self, tmp_path):
        repo = tmp_path / "emily-oracle"
        repo.mkdir()
        result = scan_memory_files(repo)
        assert result == []

    def test_scans_learnings(self, tmp_path, monkeypatch):
        repo = tmp_path / "emily-oracle"
        memory = repo / "ψ" / "memory" / "learnings"
        memory.mkdir(parents=True)
        (memory / "pattern.md").write_text("# Pattern", encoding="utf-8")

        monkeypatch.setattr(
            migrator_mod,
            "extract_metadata",
            lambda fp, rp: {"oracle_name": "emily", "doc_type": "learning", "brain_tier": "extrinsic", "scope": "emily"},
        )

        result = scan_memory_files(repo)
        assert len(result) == 1
        assert result[0]["rel_path"] == str(Path("ψ/memory/learnings/pattern.md"))
        assert result[0]["oracle"] == "emily"
        assert result[0]["doc_type"] == "learning"

    def test_scans_retrospectives(self, tmp_path, monkeypatch):
        repo = tmp_path / "emily-oracle"
        memory = repo / "ψ" / "memory" / "retrospectives" / "2026" / "05"
        memory.mkdir(parents=True)
        (memory / "retro.md").write_text("# Retro", encoding="utf-8")

        monkeypatch.setattr(
            migrator_mod,
            "extract_metadata",
            lambda fp, rp: {"oracle_name": "emily", "doc_type": "retro", "brain_tier": "extrinsic"},
        )

        result = scan_memory_files(repo)
        assert len(result) == 1
        assert result[0]["doc_type"] == "retro"

    def test_skips_memory_md(self, tmp_path, monkeypatch):
        repo = tmp_path / "emily-oracle"
        memory = repo / "ψ" / "memory" / "learnings"
        memory.mkdir(parents=True)
        (memory / "MEMORY.md").write_text("# Memory", encoding="utf-8")
        (memory / "note.md").write_text("# Note", encoding="utf-8")

        monkeypatch.setattr(
            migrator_mod,
            "extract_metadata",
            lambda fp, rp: {"oracle_name": "emily", "doc_type": "learning", "brain_tier": "extrinsic"},
        )

        result = scan_memory_files(repo)
        assert len(result) == 1
        assert result[0]["path"].name == "note.md"

    def test_uses_defaults_when_meta_missing(self, tmp_path, monkeypatch):
        repo = tmp_path / "emily-oracle"
        memory = repo / "ψ" / "memory" / "knowledge"
        memory.mkdir(parents=True)
        (memory / "note.md").write_text("# Note", encoding="utf-8")

        monkeypatch.setattr(
            migrator_mod,
            "extract_metadata",
            lambda fp, rp: {},
        )

        result = scan_memory_files(repo)
        assert result[0]["oracle"] == "emily"
        assert result[0]["doc_type"] == "learning"
        assert result[0]["brain_tier"] == "extrinsic"
        assert result[0]["scope"] == "shared"

    def test_empty_subdir_returns_empty(self, tmp_path):
        repo = tmp_path / "emily-oracle"
        memory = repo / "ψ" / "memory" / "learnings"
        memory.mkdir(parents=True)
        result = scan_memory_files(repo)
        assert result == []


class TestMigrate:
    @pytest.mark.asyncio
    async def test_migrate_dry_run(self, tmp_path, monkeypatch):
        repo = tmp_path / "emily-oracle"
        memory = repo / "ψ" / "memory" / "learnings"
        memory.mkdir(parents=True)
        (memory / "pattern.md").write_text("# Pattern", encoding="utf-8")

        monkeypatch.setattr(migrator_mod, "KNOWN_ORACLES", ["emily-oracle"])
        monkeypatch.setattr(migrator_mod, "ORACLE_REPOS", tmp_path)
        monkeypatch.setattr(
            migrator_mod,
            "extract_metadata",
            lambda fp, rp: {"oracle_name": "emily", "doc_type": "learning", "brain_tier": "extrinsic", "scope": "emily"},
        )

        push = MagicMock()

        stats = await migrate(push, repo_filter="emily-oracle", dry_run=True)

        assert stats["scanned"] == 1
        assert stats["imported"] == 0
        push.push_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_migrate_imports_files(self, tmp_path, monkeypatch):
        repo = tmp_path / "emily-oracle"
        memory = repo / "ψ" / "memory" / "learnings"
        memory.mkdir(parents=True)
        (memory / "pattern.md").write_text("# Pattern", encoding="utf-8")

        monkeypatch.setattr(migrator_mod, "KNOWN_ORACLES", ["emily-oracle"])
        monkeypatch.setattr(migrator_mod, "ORACLE_REPOS", tmp_path)
        monkeypatch.setattr(
            migrator_mod,
            "extract_metadata",
            lambda fp, rp: {"oracle_name": "emily", "doc_type": "learning", "brain_tier": "extrinsic", "scope": "emily"},
        )

        push = MagicMock()
        push.push_file = AsyncMock(return_value={"id": "doc-1", "status": "indexed"})

        stats = await migrate(push, dry_run=False)

        assert stats["scanned"] == 1
        assert stats["imported"] == 1
        assert stats["duplicate"] == 0
        assert stats["error"] == 0
        push.push_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_migrate_counts_duplicates(self, tmp_path, monkeypatch):
        repo = tmp_path / "emily-oracle"
        memory = repo / "ψ" / "memory" / "learnings"
        memory.mkdir(parents=True)
        (memory / "dup.md").write_text("# Dup", encoding="utf-8")

        monkeypatch.setattr(migrator_mod, "KNOWN_ORACLES", ["emily-oracle"])
        monkeypatch.setattr(migrator_mod, "ORACLE_REPOS", tmp_path)
        monkeypatch.setattr(
            migrator_mod,
            "extract_metadata",
            lambda fp, rp: {"oracle_name": "emily", "doc_type": "learning", "brain_tier": "extrinsic", "scope": "emily"},
        )

        push = MagicMock()
        push.push_file = AsyncMock(return_value={"id": "doc-1", "status": "duplicate"})

        stats = await migrate(push, dry_run=False)

        assert stats["duplicate"] == 1
        assert stats["imported"] == 0

    @pytest.mark.asyncio
    async def test_migrate_counts_errors(self, tmp_path, monkeypatch):
        repo = tmp_path / "emily-oracle"
        memory = repo / "ψ" / "memory" / "learnings"
        memory.mkdir(parents=True)
        (memory / "bad.md").write_text("# Bad", encoding="utf-8")

        monkeypatch.setattr(migrator_mod, "KNOWN_ORACLES", ["emily-oracle"])
        monkeypatch.setattr(migrator_mod, "ORACLE_REPOS", tmp_path)
        monkeypatch.setattr(
            migrator_mod,
            "extract_metadata",
            lambda fp, rp: {"oracle_name": "emily", "doc_type": "learning", "brain_tier": "extrinsic", "scope": "emily"},
        )

        push = MagicMock()
        push.push_file = AsyncMock(side_effect=RuntimeError("push failed"))

        stats = await migrate(push, dry_run=False)

        assert stats["error"] == 1
        assert stats["imported"] == 0

    @pytest.mark.asyncio
    async def test_migrate_repo_filter(self, tmp_path, monkeypatch):
        repo_a = tmp_path / "emily-oracle"
        memory_a = repo_a / "ψ" / "memory" / "learnings"
        memory_a.mkdir(parents=True)
        (memory_a / "a.md").write_text("# A", encoding="utf-8")

        repo_b = tmp_path / "nexus-oracle"
        memory_b = repo_b / "ψ" / "memory" / "learnings"
        memory_b.mkdir(parents=True)
        (memory_b / "b.md").write_text("# B", encoding="utf-8")

        monkeypatch.setattr(migrator_mod, "KNOWN_ORACLES", ["emily-oracle", "nexus-oracle"])
        monkeypatch.setattr(migrator_mod, "ORACLE_REPOS", tmp_path)
        monkeypatch.setattr(
            migrator_mod,
            "extract_metadata",
            lambda fp, rp: {"oracle_name": "emily", "doc_type": "learning", "brain_tier": "extrinsic", "scope": "emily"},
        )

        push = MagicMock()
        push.push_file = AsyncMock(return_value={"id": "doc-1", "status": "indexed"})

        stats = await migrate(push, repo_filter="emily-oracle", dry_run=False)

        assert stats["scanned"] == 1
        assert stats["imported"] == 1
        assert push.push_file.call_count == 1

    @pytest.mark.asyncio
    async def test_migrate_missing_repo_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(migrator_mod, "KNOWN_ORACLES", ["missing-oracle"])
        monkeypatch.setattr(migrator_mod, "ORACLE_REPOS", tmp_path)

        push = MagicMock()

        stats = await migrate(push, dry_run=False)

        assert stats["scanned"] == 0
        assert stats["imported"] == 0
        push.push_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_migrate_multiple_files(self, tmp_path, monkeypatch):
        repo = tmp_path / "emily-oracle"
        for subdir in ["learnings", "knowledge"]:
            d = repo / "ψ" / "memory" / subdir
            d.mkdir(parents=True)
            (d / "note.md").write_text(f"# {subdir}", encoding="utf-8")

        monkeypatch.setattr(migrator_mod, "KNOWN_ORACLES", ["emily-oracle"])
        monkeypatch.setattr(migrator_mod, "ORACLE_REPOS", tmp_path)
        monkeypatch.setattr(
            migrator_mod,
            "extract_metadata",
            lambda fp, rp: {"oracle_name": "emily", "doc_type": "learning", "brain_tier": "extrinsic", "scope": "emily"},
        )

        push = MagicMock()
        push.push_file = AsyncMock(return_value={"id": "doc-1", "status": "indexed"})

        stats = await migrate(push, dry_run=False)

        assert stats["scanned"] == 2
        assert stats["imported"] == 2
        assert len(push.push_file.call_args_list) == 2

    @pytest.mark.asyncio
    async def test_migrate_file_list_in_stats(self, tmp_path, monkeypatch):
        repo = tmp_path / "emily-oracle"
        memory = repo / "ψ" / "memory" / "learnings"
        memory.mkdir(parents=True)
        (memory / "pattern.md").write_text("# Pattern", encoding="utf-8")

        monkeypatch.setattr(migrator_mod, "KNOWN_ORACLES", ["emily-oracle"])
        monkeypatch.setattr(migrator_mod, "ORACLE_REPOS", tmp_path)
        monkeypatch.setattr(
            migrator_mod,
            "extract_metadata",
            lambda fp, rp: {"oracle_name": "emily", "doc_type": "learning", "brain_tier": "extrinsic", "scope": "emily"},
        )

        push = MagicMock()
        push.push_file = AsyncMock(return_value={"id": "doc-42", "status": "indexed"})

        stats = await migrate(push, dry_run=False)

        assert len(stats["files"]) == 1
        assert stats["files"][0]["id"] == "doc-42"
        assert stats["files"][0]["oracle"] == "emily"

    @pytest.mark.asyncio
    async def test_migrate_no_filter_runs_all_known(self, tmp_path, monkeypatch):
        for name in ["emily-oracle", "nexus-oracle"]:
            repo = tmp_path / name
            memory = repo / "ψ" / "memory" / "learnings"
            memory.mkdir(parents=True)
            (memory / "note.md").write_text("# Note", encoding="utf-8")

        monkeypatch.setattr(migrator_mod, "KNOWN_ORACLES", ["emily-oracle", "nexus-oracle"])
        monkeypatch.setattr(migrator_mod, "ORACLE_REPOS", tmp_path)
        monkeypatch.setattr(
            migrator_mod,
            "extract_metadata",
            lambda fp, rp: {"oracle_name": "emily", "doc_type": "learning", "brain_tier": "extrinsic", "scope": "emily"},
        )

        push = MagicMock()
        push.push_file = AsyncMock(return_value={"id": "doc-1", "status": "indexed"})

        stats = await migrate(push, dry_run=False)

        assert stats["scanned"] == 2
        assert stats["imported"] == 2
