"""Tests for registry — project registration, scope detection, backup/restore."""

import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src import registry as registry_mod
from src.registry import (
    detect_scope,
    validate_scope,
    register_project,
    unregister_project,
    list_projects,
    get_all_scopes,
    restore_registry_backup,
    _save_registry_backup,
)


class TestDetectScope:
    def test_github_path(self):
        assert detect_scope("/home/user/github.com/doctorboyz/synapse") == "synapse"

    def test_code_path(self):
        assert detect_scope("/Users/doctorboyz/Code/synapse") == "synapse"

    def test_plain_path(self):
        assert detect_scope("/Users/doctorboyz/my-project") == "my-project"

    def test_sanitizes_special_chars(self):
        assert detect_scope("/tmp/My_Project!!!") == "my-project"

    def test_collapses_multiple_dashes(self):
        assert detect_scope("/tmp/a---b") == "a-b"

    def test_strips_leading_trailing_dashes(self):
        assert detect_scope("/tmp/-project-") == "project"

    def test_fallback_shared_when_empty(self):
        assert detect_scope("/tmp/!!!") == "shared"


class TestValidateScope:
    def test_valid_scope(self):
        assert validate_scope("my-project") is True

    def test_valid_single_char(self):
        assert validate_scope("a") is True

    def test_valid_numeric(self):
        assert validate_scope("project123") is True

    def test_invalid_uppercase(self):
        assert validate_scope("My-Project") is False

    def test_invalid_underscore(self):
        assert validate_scope("my_project") is False

    def test_invalid_starts_with_dash(self):
        assert validate_scope("-project") is False

    def test_invalid_empty(self):
        assert validate_scope("") is False

    def test_invalid_too_long(self):
        assert validate_scope("a" * 65) is False

    def test_invalid_max_boundary_ok(self):
        assert validate_scope("a" * 64) is True


class TestRegisterProject:
    @pytest.mark.asyncio
    async def test_register_auto_detects_scope(self, monkeypatch):
        mock_pg = MagicMock()
        mock_conn = AsyncMock()
        mock_pg.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pg.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr(registry_mod, "_save_registry_backup", AsyncMock())

        result = await register_project(mock_pg, "/home/user/Code/my-project")

        assert result["project_name"] == "my-project"
        assert result["status"] == "registered"
        mock_conn.execute.assert_called_once()
        args = mock_conn.execute.call_args[0]
        assert "INSERT INTO registered_projects" in args[0]
        assert "my-project" in args[1:]

    @pytest.mark.asyncio
    async def test_register_with_explicit_scope(self, monkeypatch):
        mock_pg = MagicMock()
        mock_conn = AsyncMock()
        mock_pg.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pg.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr(registry_mod, "_save_registry_backup", AsyncMock())

        result = await register_project(mock_pg, "/some/path", scope="custom-scope")

        assert result["project_name"] == "custom-scope"

    @pytest.mark.asyncio
    async def test_register_invalid_scope_raises(self):
        mock_pg = MagicMock()
        with pytest.raises(ValueError, match="Invalid project name"):
            await register_project(mock_pg, "/some/path", scope="INVALID_SCOPE")


class TestUnregisterProject:
    @pytest.mark.asyncio
    async def test_unregister_success(self, monkeypatch):
        mock_pg = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = "DELETE 1"
        mock_pg.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pg.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr(registry_mod, "_save_registry_backup", AsyncMock())

        result = await unregister_project(mock_pg, "my-project")

        assert result["project_name"] == "my-project"
        assert result["status"] == "unregistered"
        mock_conn.execute.assert_called_once_with(
            "DELETE FROM registered_projects WHERE scope = $1", "my-project"
        )

    @pytest.mark.asyncio
    async def test_unregister_not_found(self):
        mock_pg = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = "DELETE 0"
        mock_pg.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pg.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await unregister_project(mock_pg, "missing-project")

        assert result["status"] == "not_found"


class TestListProjects:
    @pytest.mark.asyncio
    async def test_list_projects_maps_rows(self):
        mock_pg = MagicMock()
        mock_conn = AsyncMock()
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {"scope": "s1", "project_path": "/p1", "registered_at": datetime(2025, 1, 1)}[key]
        mock_conn.fetch.return_value = [mock_row]
        mock_pg.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pg.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await list_projects(mock_pg)

        assert len(result) == 1
        assert result[0]["project_name"] == "s1"
        assert result[0]["project_path"] == "/p1"
        assert result[0]["registered_at"] == "2025-01-01 00:00:00"


class TestGetAllScopes:
    @pytest.mark.asyncio
    async def test_get_all_scopes_returns_list(self):
        mock_pg = MagicMock()
        mock_conn = AsyncMock()
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: "s1" if key == "scope" else None
        mock_conn.fetch.return_value = [mock_row]
        mock_pg.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pg.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await get_all_scopes(mock_pg)

        assert result == ["s1"]


class TestSaveRegistryBackup:
    @pytest.mark.asyncio
    async def test_saves_json_backup(self, tmp_path, monkeypatch):
        mock_pg = MagicMock()

        async def fake_list_projects(pg):
            return [{"scope": "s1", "project_path": "/p1", "registered_at": "2025-01-01T00:00:00"}]

        monkeypatch.setattr(registry_mod, "list_projects", fake_list_projects)
        backup_path = tmp_path / "projects.json"

        await _save_registry_backup(mock_pg, path=backup_path)

        assert backup_path.exists()
        data = json.loads(backup_path.read_text(encoding="utf-8"))
        assert data["projects"][0]["scope"] == "s1"
        assert "saved_at" in data

    @pytest.mark.asyncio
    async def test_save_backup_graceful_error(self, tmp_path, monkeypatch):
        mock_pg = MagicMock()

        async def fake_list_projects(pg):
            raise RuntimeError("db down")

        monkeypatch.setattr(registry_mod, "list_projects", fake_list_projects)
        backup_path = tmp_path / "projects.json"

        # Should not raise
        await _save_registry_backup(mock_pg, path=backup_path)


class TestRestoreRegistryBackup:
    @pytest.mark.asyncio
    async def test_no_backup_file(self):
        mock_pg = MagicMock()
        result = await restore_registry_backup(mock_pg, path=Path("/nonexistent/backup.json"))
        assert result["reason"] == "no_backup"
        assert result["restored"] == 0

    @pytest.mark.asyncio
    async def test_db_not_empty(self, tmp_path, monkeypatch):
        mock_pg = MagicMock()

        async def fake_list_projects(pg):
            return [{"scope": "s1", "project_path": "/p1", "registered_at": "2025-01-01T00:00:00"}]

        monkeypatch.setattr(registry_mod, "list_projects", fake_list_projects)
        backup_path = tmp_path / "projects.json"
        backup_path.write_text(json.dumps({"projects": []}), encoding="utf-8")

        result = await restore_registry_backup(mock_pg, path=backup_path)
        assert result["reason"] == "db_not_empty"
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_restore_success(self, tmp_path, monkeypatch):
        mock_pg = MagicMock()
        monkeypatch.setattr(registry_mod, "list_projects", AsyncMock(return_value=[]))
        monkeypatch.setattr(registry_mod, "register_project", AsyncMock(return_value={"status": "registered"}))

        backup_path = tmp_path / "projects.json"
        data = {
            "projects": [
                {"scope": "s1", "project_path": str(tmp_path), "registered_at": "2025-01-01T00:00:00"},
            ]
        }
        backup_path.write_text(json.dumps(data), encoding="utf-8")

        result = await restore_registry_backup(mock_pg, path=backup_path)
        assert result["restored"] == 1
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_restore_skips_missing_path(self, tmp_path, monkeypatch):
        mock_pg = MagicMock()
        monkeypatch.setattr(registry_mod, "list_projects", AsyncMock(return_value=[]))

        backup_path = tmp_path / "projects.json"
        data = {
            "projects": [
                {"scope": "s1", "project_path": "/nonexistent/path/nowhere", "registered_at": "2025-01-01T00:00:00"},
            ]
        }
        backup_path.write_text(json.dumps(data), encoding="utf-8")

        result = await restore_registry_backup(mock_pg, path=backup_path)
        assert result["restored"] == 0
        assert result["errors"] == 1

    @pytest.mark.asyncio
    async def test_restore_missing_fields(self, tmp_path, monkeypatch):
        mock_pg = MagicMock()
        monkeypatch.setattr(registry_mod, "list_projects", AsyncMock(return_value=[]))

        backup_path = tmp_path / "projects.json"
        data = {
            "projects": [
                {"scope": "s1"},  # missing project_path
            ]
        }
        backup_path.write_text(json.dumps(data), encoding="utf-8")

        result = await restore_registry_backup(mock_pg, path=backup_path)
        assert result["restored"] == 0
        assert result["errors"] == 1

    @pytest.mark.asyncio
    async def test_restore_read_error(self, tmp_path, monkeypatch):
        mock_pg = MagicMock()
        monkeypatch.setattr(registry_mod, "list_projects", AsyncMock(return_value=[]))

        backup_path = tmp_path / "projects.json"
        backup_path.write_text("not json", encoding="utf-8")

        result = await restore_registry_backup(mock_pg, path=backup_path)
        assert result["reason"] == "read_error"
        assert result["errors"] == 1
