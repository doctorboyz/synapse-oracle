"""Oracle path mapping — kappa/psi brain structure to synapse metadata."""

import re
from pathlib import Path

ORACLE_PATH_RULES: list[tuple[str, str, str]] = [
    (r"ψ/memory/learnings/", "learning", "extrinsic"),
    (r"ψ/memory/retrospectives/", "retro", "extrinsic"),
    (r"ψ/outbox/", "handoff", "extrinsic"),
    (r"κ/extrinsic/wisdom/knowledge/", "wisdom", "extrinsic"),
    (r"κ/extrinsic/wisdom/reference/", "reference", "extrinsic"),
    (r"κ/extrinsic/experience/learn/", "learning", "extrinsic"),
    (r"κ/extrinsic/experience/work/logs/", "log", "extrinsic"),
    (r"κ/intrinsic/instinct/", "instinct", "intrinsic"),
    (r"κ/intrinsic/identity/", "instinct", "intrinsic"),
    (r"κ/intrinsic/inherit/", "instinct", "intrinsic"),
]

VALID_DOC_TYPES = {
    "learning", "pattern", "retro", "reference", "handoff",
    "protocol", "wisdom", "instinct", "log", "note", "task",
}

VALID_TRACE_RELATIONS = {"derived_from", "refines", "contradicts", "extends", "references"}


def extract_oracle_name(repo_path: str) -> str:
    basename = Path(repo_path).name
    return basename.replace("-oracle", "")


def extract_metadata(file_path: str, repo_root: str) -> dict:
    rel_path = str(file_path).replace(str(repo_root) + "/", "")
    oracle_name = extract_oracle_name(repo_root)

    for pattern, doc_type, brain_tier in ORACLE_PATH_RULES:
        if pattern in rel_path:
            return {
                "oracle_name": oracle_name,
                "brain_path": rel_path,
                "brain_tier": brain_tier,
                "doc_type": doc_type,
                "scope": oracle_name,
            }

    return {
        "oracle_name": oracle_name,
        "brain_path": rel_path,
        "brain_tier": "extrinsic",
        "doc_type": "note",
        "scope": oracle_name,
    }


def validate_doc_type(doc_type: str) -> str:
    if doc_type not in VALID_DOC_TYPES:
        raise ValueError(f"Invalid doc_type '{doc_type}'. Must be one of: {sorted(VALID_DOC_TYPES)}")
    return doc_type


def validate_trace_relation(relation: str) -> str:
    if relation not in VALID_TRACE_RELATIONS:
        raise ValueError(f"Invalid relation '{relation}'. Must be one of: {sorted(VALID_TRACE_RELATIONS)}")
    return relation