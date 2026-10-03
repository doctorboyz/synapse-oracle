"""Oracle path mapping — kappa/psi brain structure to synapse metadata.

Document types are organized into two families:
- Content-based: knowledge, understanding, memory (no status lifecycle)
- Event-based: actions, events, deadlines (have status and dates)

See docs/doctypeguideline.md for the full specification.
"""

from pathlib import Path

# ─── Oracle path → doc_type + brain_tier mapping ────────────────────────

ORACLE_PATH_RULES: list[tuple[str, str, str]] = [
    # Content-based (knowledge, understanding, memory)
    (r"ψ/memory/learnings/", "knowledge", "extrinsic"),
    (r"ψ/memory/retrospectives/", "retro", "extrinsic"),
    (r"ψ/outbox/", "handoff", "extrinsic"),
    (r"κ/extrinsic/wisdom/knowledge/", "knowledge", "extrinsic"),
    (r"κ/extrinsic/wisdom/reference/", "reference", "extrinsic"),
    (r"κ/extrinsic/experience/learn/", "knowledge", "extrinsic"),
    (r"κ/extrinsic/experience/work/logs/", "log", "extrinsic"),
    (r"κ/intrinsic/instinct/", "instinct", "intrinsic"),
    (r"κ/intrinsic/identity/", "instinct", "intrinsic"),
    (r"κ/intrinsic/inherit/", "instinct", "intrinsic"),
]

# ─── Document type families ────────────────────────────────────────────

CONTENT_TYPES = {
    # Knowledge and understanding (no expiry, no status)
    "knowledge",    # Lesson learned, reusable
    "note",         # Unclassified capture (default)
    "idea",          # New thought, not yet validated
    "insight",      # Moment of clarity
    "moment",       # Experience worth remembering
    "good-to-know", # Useful later, not needed now
    "reference",    # External source citation
    # Structured content
    "retro",        # Retrospective
    "pattern",      # Recognized recurring pattern
    "protocol",     # Rule or procedure
    "instinct",     # Deeply internalized knowledge
    "wisdom",       # Distilled truth from experience
    "handoff",      # Knowledge passed between sessions/people
    "log",          # Chronological record
}

EVENT_TYPES = {
    # Actions and events (have dates, have status lifecycle)
    "todo",         # Something to do with a deadline
    "not-to-do",   # Something explicitly forbidden
    "reminder",     # A nudge at a specific time
    "event",        # Something that already happened
    "payment",      # Money going out or coming in
    "deadline",     # Hard delivery date with consequences
}

VALID_DOC_TYPES = CONTENT_TYPES | EVENT_TYPES

# Legacy alias — task → todo
_DOC_TYPE_ALIASES = {
    "task": "todo",
    "learning": "knowledge",
}

VALID_TRACE_RELATIONS = {"derived_from", "refines", "contradicts", "extends", "references"}


def extract_oracle_name(repo_path: str) -> str:
    basename = Path(repo_path).name
    return basename.replace("-oracle", "")


def extract_metadata(file_path: str, repo_root: str) -> dict:
    """Extract doc_type, oracle_name, and metadata from a vault file path.

    Returns a dict with:
    - oracle_name: derived from repo path
    - doc_type: content-based or event-based type
    - tags: namespace tags
    - metadata: JSONB-ready dict with brain_path, brain_tier, etc.
    """
    rel_path = str(file_path).replace(str(repo_root) + "/", "")
    oracle_name = extract_oracle_name(repo_root)

    for pattern, doc_type, brain_tier in ORACLE_PATH_RULES:
        if pattern in rel_path:
            return {
                "oracle_name": oracle_name,
                "doc_type": doc_type,
                "tags": [f"oracle:{oracle_name}"],
                "metadata": {
                    "brain_path": rel_path,
                    "brain_tier": brain_tier,
                },
            }

    return {
        "oracle_name": oracle_name,
        "doc_type": "note",
        "tags": [f"oracle:{oracle_name}"],
        "metadata": {
            "brain_path": rel_path,
            "brain_tier": "extrinsic",
        },
    }


def validate_doc_type(doc_type: str) -> str:
    """Validate and normalize doc_type. Resolves legacy aliases."""
    normalized = _DOC_TYPE_ALIASES.get(doc_type, doc_type)
    if normalized not in VALID_DOC_TYPES:
        raise ValueError(
            f"Invalid doc_type '{doc_type}'. "
            f"Content types: {sorted(CONTENT_TYPES)}. "
            f"Event types: {sorted(EVENT_TYPES)}."
        )
    return normalized


def is_content_type(doc_type: str) -> bool:
    """Check if doc_type is content-based (knowledge, note, idea, etc.)."""
    return doc_type in CONTENT_TYPES


def is_event_type(doc_type: str) -> bool:
    """Check if doc_type is event-based (todo, reminder, payment, etc.)."""
    return doc_type in EVENT_TYPES


def validate_trace_relation(relation: str) -> str:
    if relation not in VALID_TRACE_RELATIONS:
        raise ValueError(f"Invalid relation '{relation}'. Must be one of: {sorted(VALID_TRACE_RELATIONS)}")
    return relation