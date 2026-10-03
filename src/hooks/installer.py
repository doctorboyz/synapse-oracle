"""Hook installer — register synapse hooks in ~/.claude/settings.json."""

import json
import logging
from pathlib import Path

log = logging.getLogger("synapse.hooks")

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

# Marker string for idempotency checks
SYNAPSE_CONTEXT_MARKER = "synapse-context-inject"


def load_settings(path: Path | None = None) -> dict:
    """Load settings.json, return empty dict if not found."""
    path = path or SETTINGS_PATH
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.error("Failed to read %s: %s", path, e)
        return {}


def save_settings(settings: dict, path: Path | None = None) -> None:
    """Save settings.json with pretty formatting."""
    path = path or SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def find_hook_entry(hooks_list: list, marker: str) -> dict | None:
    """Find a hook entry containing the marker string in any command."""
    for entry in hooks_list:
        if "hooks" not in entry:
            continue
        for hook in entry["hooks"]:
            cmd = hook.get("command", "")
            if marker in cmd:
                return entry
    return None


def build_context_inject_hook_entry(script_path: str | None = None) -> dict:
    """Build the PreToolUse context injection hook entry."""
    if script_path is None:
        script_path = str(Path(__file__).parent / "synapse-context-inject.sh")
    return {
        "matcher": "Read|Glob|Grep",
        "hooks": [
            {
                "type": "command",
                "command": f'bash "{script_path}"',
                "timeout": 5,
            }
        ],
    }


def install_hooks(
    settings_path: Path | None = None,
    script_path: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Install synapse hooks into settings.json. Returns report dict."""
    path = settings_path or SETTINGS_PATH
    settings = load_settings(path)

    if "hooks" not in settings:
        settings["hooks"] = {}

    results = {
        "settings_path": str(path),
        "context_hook": "unchanged",
        "changes": [],
    }

    # PreToolUse: context injection
    pre_hooks = settings["hooks"].setdefault("PreToolUse", [])
    existing_context = find_hook_entry(pre_hooks, SYNAPSE_CONTEXT_MARKER)

    if existing_context is None:
        context_entry = build_context_inject_hook_entry(script_path)
        pre_hooks.append(context_entry)
        results["context_hook"] = "installed"
        results["changes"].append("Added PreToolUse context injection hook")
    else:
        results["context_hook"] = "already_exists"

    if not dry_run and results["changes"]:
        save_settings(settings, path)

    if dry_run:
        results["dry_run"] = True

    return results