"""Tests for concept extraction — hashtags and PascalCase identifiers."""

import pytest

from src.ingest.concepts import extract_concepts


class TestExtractConcepts:
    def test_extract_concepts_empty_string_returns_empty(self):
        assert extract_concepts("") == []

    def test_extract_concepts_no_matches_returns_empty(self):
        assert extract_concepts("hello world plain text") == []

    def test_extract_concepts_single_hashtag(self):
        result = extract_concepts("#python")
        assert result == ["python"]

    def test_extract_concepts_multiple_hashtags(self):
        result = extract_concepts("#python #async-programming #web_dev")
        assert result == ["async programming", "python", "web dev"]

    def test_extract_concepts_hashtag_with_underscores_and_hyphens(self):
        result = extract_concepts("#hello_world #hello-world")
        assert result == ["hello world"]

    def test_extract_concepts_single_pascalcase(self):
        result = extract_concepts("HybridSearch")
        assert result == ["HybridSearch"]

    def test_extract_concepts_multiple_pascalcase(self):
        result = extract_concepts("HybridSearch VectorStore PgStore")
        assert result == ["HybridSearch", "PgStore", "VectorStore"]

    def test_extract_concepts_camelcase_excluded(self):
        # camelCase starting with lowercase does NOT match the PascalCase regex
        result = extract_concepts("hybridSearch")
        assert result == []

    def test_extract_concepts_single_word_excluded(self):
        # Single capitalized word does not match PascalCase regex
        result = extract_concepts("Python")
        assert result == []

    def test_extract_concepts_mixed_hashtags_and_pascalcase(self):
        content = "Use #hybrid-search with HybridSearch for best results. #knowledge-graph"
        result = extract_concepts(content)
        assert "hybrid search" in result
        assert "knowledge graph" in result
        assert "HybridSearch" in result

    def test_extract_concepts_deduplicates_hashtags(self):
        result = extract_concepts("#python #python #PYTHON")
        assert result == ["python"]

    def test_extract_concepts_deduplicates_pascalcase(self):
        result = extract_concepts("HybridSearch and HybridSearch again")
        assert result == ["HybridSearch"]

    def test_extract_concepts_deduplicates_across_types(self):
        # Hashtag converted to lowercase, PascalCase stays as-is
        result = extract_concepts("#HybridSearch and HybridSearch")
        assert result == ["HybridSearch", "hybridsearch"]

    def test_extract_concepts_numbers_in_hashtags(self):
        result = extract_concepts("#python3 #async2")
        assert result == ["async2", "python3"]

    def test_extract_concepts_numbers_in_pascalcase(self):
        # Numbers must appear after the second uppercase letter
        result = extract_concepts("HelloWorld2 PythonA3sync")
        assert result == ["HelloWorld2", "PythonA3sync"]

    def test_extract_concepts_hashtag_must_start_with_letter(self):
        # #3python should not match because hashtag must start with letter
        result = extract_concepts("#3python")
        assert result == []

    def test_extract_concepts_sorted_order(self):
        result = extract_concepts("#zebra #alpha #mike")
        assert result == ["alpha", "mike", "zebra"]

    def test_extract_concepts_special_chars_around_hashtags(self):
        result = extract_concepts("Check out (#python) and #async!")
        assert result == ["async", "python"]
