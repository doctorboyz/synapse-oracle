"""Tests for Claude ingest pipeline — claude_hook.py."""

from pathlib import Path


class TestIsVaultFile:
    def test_kappa_directory(self):
        from src.ingest.claude_hook import _is_vault_file

        assert _is_vault_file(Path("/some/project/κ/learnings/test.md")) is True

    def test_psi_directory(self):
        from src.ingest.claude_hook import _is_vault_file

        assert _is_vault_file(Path("/some/project/ψ/memory/roadmap.md")) is True

    def test_non_vault_file(self):
        from src.ingest.claude_hook import _is_vault_file

        assert _is_vault_file(Path("/some/project/src/main.py")) is False

    def test_md_file_outside_vault(self):
        from src.ingest.claude_hook import _is_vault_file

        # .md files outside κ/ψ directories are NOT vault files
        assert _is_vault_file(Path("/tmp/random.md")) is False

    def test_kappa_in_middle_of_path(self):
        from src.ingest.claude_hook import _is_vault_file

        assert _is_vault_file(Path("/home/user/projects/oracle/κ/inbox/note.md")) is True


class TestResolveSourceProject:
    def test_kappa_project(self):
        from src.ingest.claude_hook import _resolve_source_project

        path = Path("/home/user/projects/my-oracle/κ/learnings/test.md")
        assert _resolve_source_project(path) == "my-oracle"

    def test_psi_project(self):
        from src.ingest.claude_hook import _resolve_source_project

        path = Path("/opt/oracles/synapse/ψ/memory/roadmap.md")
        assert _resolve_source_project(path) == "synapse"

    def test_no_vault_dir(self):
        from src.ingest.claude_hook import _resolve_source_project

        path = Path("/tmp/random.md")
        assert _resolve_source_project(path) == "unknown"


class TestExtractTaskInfo:
    def test_detect_relative_days(self):
        from src.assistant.tag_rules import _extract_task_info_from_content

        result = _extract_task_info_from_content("Complete this within 3 days")
        assert result["is_task"] is True
        assert result["due_date"] is not None

    def test_detect_iso_date(self):
        from src.assistant.tag_rules import _extract_task_info_from_content

        result = _extract_task_info_from_content("Submit report due: 2026-06-15")
        assert result["is_task"] is True
        assert "2026-06-15" in result["due_date"]

    def test_detect_tomorrow(self):
        from src.assistant.tag_rules import _extract_task_info_from_content

        result = _extract_task_info_from_content("Do this tomorrow please")
        assert result["is_task"] is True
        assert result["due_date"] is not None

    def test_detect_urgency(self):
        from src.assistant.tag_rules import _extract_task_info_from_content

        result = _extract_task_info_from_content("URGENT: Fix the server crash")
        assert result["priority"] == "high"

    def test_detect_low_priority(self):
        from src.assistant.tag_rules import _extract_task_info_from_content

        result = _extract_task_info_from_content("Nice to have: update docs")
        assert result["priority"] == "low"

    def test_default_priority(self):
        from src.assistant.tag_rules import _extract_task_info_from_content

        result = _extract_task_info_from_content("Regular task with no priority markers")
        assert result["priority"] == "medium"

    def test_thai_month(self):
        from src.assistant.tag_rules import _extract_task_info_from_content

        result = _extract_task_info_from_content("ส่งงานภายใน 15 ม.ค.")
        assert result["is_task"] is True

    def test_thai_today(self):
        from src.assistant.tag_rules import _extract_task_info_from_content

        result = _extract_task_info_from_content("วันนี้ต้องทำ")
        assert result["is_task"] is True
