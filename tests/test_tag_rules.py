"""Tests for tag_rules engine — CRUD, seeding, rule application."""

import pytest


@pytest.mark.asyncio
class TestTagRulesCRUD:
    async def test_upsert_tag_rule(self, clean_pg):
        result = await clean_pg.upsert_tag_rule(
            tag_name="test_rule",
            handler="task",
            description="Test rule for CRUD",
            auto_classify=True,
            alert_on_due=False,
        )
        assert result["tag_name"] == "test_rule"
        assert result["handler"] == "task"
        assert result["enabled"] is True

    async def test_get_tag_rule(self, clean_pg):
        await clean_pg.upsert_tag_rule(
            tag_name="get_test",
            handler="task",
            description="Get test rule",
        )
        rule = await clean_pg.get_tag_rule("get_test")
        assert rule is not None
        assert rule["tag_name"] == "get_test"
        assert rule["handler"] == "task"

    async def test_get_nonexistent_rule(self, clean_pg):
        rule = await clean_pg.get_tag_rule("nonexistent")
        assert rule is None

    async def test_list_tag_rules(self, clean_pg):
        await clean_pg.upsert_tag_rule(tag_name="list_a", handler="task")
        await clean_pg.upsert_tag_rule(tag_name="list_b", handler="calendar")
        rules = await clean_pg.list_tag_rules()
        assert len(rules) >= 2
        names = [r["tag_name"] for r in rules]
        assert "list_a" in names
        assert "list_b" in names

    async def test_list_enabled_only(self, clean_pg):
        await clean_pg.upsert_tag_rule(tag_name="enabled_rule", handler="task", enabled=True)
        await clean_pg.upsert_tag_rule(tag_name="disabled_rule", handler="task", enabled=False)
        rules = await clean_pg.list_tag_rules(enabled_only=True)
        names = [r["tag_name"] for r in rules]
        assert "enabled_rule" in names
        assert "disabled_rule" not in names

    async def test_upsert_updates_existing(self, clean_pg):
        await clean_pg.upsert_tag_rule(
            tag_name="update_test",
            handler="task",
            description="Original",
        )
        updated = await clean_pg.upsert_tag_rule(
            tag_name="update_test",
            handler="calendar",
            description="Updated",
        )
        assert updated["handler"] == "calendar"
        rule = await clean_pg.get_tag_rule("update_test")
        assert rule["description"] == "Updated"
        assert rule["handler"] == "calendar"

    async def test_delete_tag_rule(self, clean_pg):
        await clean_pg.upsert_tag_rule(tag_name="delete_me", handler="task")
        deleted = await clean_pg.delete_tag_rule("delete_me")
        assert deleted is True
        rule = await clean_pg.get_tag_rule("delete_me")
        assert rule is None


@pytest.mark.asyncio
class TestSeedDefaultRules:
    async def test_seed_creates_rules(self, clean_pg):
        from src.assistant.tag_rules import seed_default_rules, DEFAULT_RULES

        await seed_default_rules(clean_pg)

        for default in DEFAULT_RULES:
            rule = await clean_pg.get_tag_rule(default["tag_name"])
            assert rule is not None, f"Missing default rule: {default['tag_name']}"
            assert rule["handler"] == default["handler"]

    async def test_seed_is_idempotent(self, clean_pg):
        from src.assistant.tag_rules import seed_default_rules

        await seed_default_rules(clean_pg)
        await seed_default_rules(clean_pg)  # second call

        rules = await clean_pg.list_tag_rules()
        # Should not create duplicates
        task_rules = [r for r in rules if r["tag_name"] == "task"]
        assert len(task_rules) == 1


@pytest.mark.asyncio
class TestApplyTagRules:
    async def test_apply_task_tag_creates_scheduled_task(self, clean_pg):
        from src.assistant.tag_rules import apply_tag_rules, seed_default_rules

        await seed_default_rules(clean_pg)

        # Add a doc
        result = await clean_pg.add(
            title="Test Task", content="This is a task due tomorrow",
            doc_type="task", tags=["task"],
        )
        doc_id = result["id"]

        actions = await apply_tag_rules(clean_pg, doc_id, ["task"], content="This is a task due tomorrow")
        assert len(actions) > 0
        assert actions[0]["rule"] == "task"
        assert actions[0]["action"] == "create_task"

    async def test_apply_tag_ignores_unknown_tags(self, clean_pg):
        from src.assistant.tag_rules import apply_tag_rules

        result = await clean_pg.add(
            title="No Rule Doc", content="Some content",
            doc_type="note", tags=["unknown_tag"],
        )
        actions = await apply_tag_rules(clean_pg, result["id"], ["unknown_tag"])
        assert len(actions) == 0

    async def test_apply_tag_skips_disabled_rules(self, clean_pg):
        from src.assistant.tag_rules import apply_tag_rules, seed_default_rules

        await seed_default_rules(clean_pg)
        # Disable the task rule
        await clean_pg.upsert_tag_rule(tag_name="task", handler="task", enabled=False)

        result = await clean_pg.add(
            title="Task With Disabled Rule", content="do something",
            doc_type="task", tags=["task"],
        )
        actions = await apply_tag_rules(clean_pg, result["id"], ["task"])
        assert len(actions) == 0
