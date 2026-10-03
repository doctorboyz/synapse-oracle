"""Tests for oracle path mapping."""

from src.ingest.oracle_paths import (
    extract_oracle_name, extract_metadata, validate_doc_type, validate_trace_relation,
    VALID_DOC_TYPES, VALID_TRACE_RELATIONS,
)


class TestExtractOracleName:
    def test_emily_oracle(self):
        assert extract_oracle_name("/path/to/emily-oracle") == "emily"

    def test_broky_oracle(self):
        assert extract_oracle_name("/path/to/broky-oracle") == "broky"

    def test_non_oracle(self):
        assert extract_oracle_name("/path/to/maw-js") == "maw-js"


class TestExtractMetadata:
    def test_psi_learnings(self):
        result = extract_metadata(
            "/repos/emily-oracle/ψ/memory/learnings/pattern-001.md",
            "/repos/emily-oracle",
        )
        assert result["doc_type"] == "knowledge"
        assert result["metadata"]["brain_tier"] == "extrinsic"
        assert result["oracle_name"] == "emily"
        assert result["tags"] == ["oracle:emily"]

    def test_psi_retrospectives(self):
        result = extract_metadata(
            "/repos/emily-oracle/ψ/memory/retrospectives/2026-05/04/12.00_test.md",
            "/repos/emily-oracle",
        )
        assert result["doc_type"] == "retro"

    def test_kappa_intrinsic(self):
        result = extract_metadata(
            "/repos/emily-oracle/κ/intrinsic/instinct/oracle.md",
            "/repos/emily-oracle",
        )
        assert result["doc_type"] == "instinct"
        assert result["metadata"]["brain_tier"] == "intrinsic"

    def test_kappa_wisdom(self):
        result = extract_metadata(
            "/repos/emily-oracle/κ/extrinsic/wisdom/knowledge/synthesis.md",
            "/repos/emily-oracle",
        )
        assert result["doc_type"] == "knowledge"
        assert result["metadata"]["brain_tier"] == "extrinsic"

    def test_psi_outbox(self):
        result = extract_metadata(
            "/repos/emily-oracle/ψ/outbox/MSG-001.md",
            "/repos/emily-oracle",
        )
        assert result["doc_type"] == "handoff"

    def test_unknown_path(self):
        result = extract_metadata(
            "/repos/emily-oracle/README.md",
            "/repos/emily-oracle",
        )
        assert result["doc_type"] == "note"


class TestValidateDocType:
    def test_valid_types(self):
        for dt in VALID_DOC_TYPES:
            assert validate_doc_type(dt) == dt

    def test_invalid_type(self):
        try:
            validate_doc_type("invalid")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


class TestValidateTraceRelation:
    def test_valid_relations(self):
        for rel in VALID_TRACE_RELATIONS:
            assert validate_trace_relation(rel) == rel

    def test_invalid_relation(self):
        try:
            validate_trace_relation("invalid")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass