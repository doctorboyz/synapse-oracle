"""Tests for local-only URL validation."""

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from src.local_only import validate_local_url, validate_all_settings, check_and_warn, LOCAL_HOSTS


class TestValidateLocalUrl:
    def test_validate_local_url_localhost_passes(self):
        assert validate_local_url("http://localhost:5432/db") == []

    def test_validate_local_url_127_0_0_1_passes(self):
        assert validate_local_url("http://127.0.0.1:5000") == []

    def test_validate_local_url_ipv6_loopback_passes(self):
        assert validate_local_url("http://[::1]:8420") == []

    def test_validate_local_url_0_0_0_0_passes(self):
        assert validate_local_url("http://0.0.0.0:8000") == []

    def test_validate_local_url_docker_internal_passes(self):
        assert validate_local_url("http://host.docker.internal:5432") == []

    def test_validate_local_url_external_fails(self):
        result = validate_local_url("http://example.com:5432")
        assert len(result) == 1
        assert "Non-localhost URL" in result[0]
        assert "example.com" in result[0]

    def test_validate_local_url_external_https_fails(self):
        result = validate_local_url("https://api.openai.com/v1")
        assert len(result) == 1
        assert "openai.com" in result[0]

    def test_validate_local_url_unix_socket_passes(self):
        # Unix socket paths have no hostname
        assert validate_local_url("/var/run/postgresql/.s.PGSQL.5432") == []

    def test_validate_local_url_empty_hostname_passes(self):
        assert validate_local_url("file:///tmp/data.txt") == []

    def test_validate_local_url_non_string_returns_error(self):
        result = validate_local_url(123)
        assert len(result) == 1
        assert "Invalid URL" in result[0]

    def test_validate_local_url_docker_allow_internal(self):
        result = validate_local_url("http://service.internal:5000", allow_docker=True)
        assert result == []

    def test_validate_local_url_docker_disallow_internal_by_default(self):
        result = validate_local_url("http://service.internal:5000", allow_docker=False)
        assert len(result) == 1
        assert "Non-localhost URL" in result[0]

    def test_validate_local_url_docker_allow_0_0_0_0(self):
        # 0.0.0.0 is always in LOCAL_HOSTS, so this passes regardless
        assert validate_local_url("http://0.0.0.0:8000", allow_docker=True) == []


@dataclass
class MockSettings:
    database_url: str
    ollama_url: str
    api_host: str


class TestValidateAllSettings:
    def test_validate_all_settings_all_local_passes(self):
        settings = MockSettings(
            database_url="postgresql://localhost:5432/synapse",
            ollama_url="http://localhost:11434",
            api_host="localhost",
        )
        assert validate_all_settings(settings) == []

    def test_validate_all_settings_external_database_fails(self):
        settings = MockSettings(
            database_url="postgresql://db.example.com:5432/synapse",
            ollama_url="http://localhost:11434",
            api_host="localhost",
        )
        result = validate_all_settings(settings)
        assert len(result) == 1
        assert "db.example.com" in result[0]

    def test_validate_all_settings_multiple_external_failures(self):
        settings = MockSettings(
            database_url="postgresql://db.example.com:5432/synapse",
            ollama_url="http://ollama.external.example:11434",
            api_host="0.0.0.0",
        )
        result = validate_all_settings(settings)
        assert len(result) == 2
        hostnames = [r for r in result]
        assert any("db.example.com" in r for r in hostnames)
        assert any("ollama.external.example" in r for r in hostnames)

    def test_validate_all_settings_external_api_host_fails(self):
        settings = MockSettings(
            database_url="postgresql://localhost:5432/synapse",
            ollama_url="http://localhost:11434",
            api_host="0.0.0.0",
        )
        # 0.0.0.0 is allowed by default
        result = validate_all_settings(settings)
        assert result == []

    def test_validate_all_settings_api_host_not_in_local_hosts(self):
        settings = MockSettings(
            database_url="postgresql://localhost:5432/synapse",
            ollama_url="http://localhost:11434",
            api_host="192.168.1.100",
        )
        result = validate_all_settings(settings)
        assert len(result) == 1
        assert "Non-localhost api_host: 192.168.1.100" in result[0]

    def test_validate_all_settings_docker_allow_0_0_0_0_api_host(self):
        settings = MockSettings(
            database_url="postgresql://localhost:5432/synapse",
            ollama_url="http://localhost:11434",
            api_host="0.0.0.0",
        )
        # allow_docker=True allows 0.0.0.0, but it's already allowed by default
        assert validate_all_settings(settings, allow_docker=True) == []

    def test_validate_all_settings_docker_disallow_external_api_host(self):
        settings = MockSettings(
            database_url="postgresql://localhost:5432/synapse",
            ollama_url="http://localhost:11434",
            api_host="192.168.1.100",
        )
        result = validate_all_settings(settings, allow_docker=True)
        assert len(result) == 1
        assert "192.168.1.100" in result[0]

    def test_validate_all_settings_ollama_external_fails(self):
        settings = MockSettings(
            database_url="postgresql://localhost:5432/synapse",
            ollama_url="http://ollama.external:11434",
            api_host="localhost",
        )
        result = validate_all_settings(settings)
        assert len(result) == 1
        assert "ollama.external" in result[0]

    def test_validate_all_settings_invalid_database_url(self):
        settings = MockSettings(
            database_url=123,
            ollama_url="http://localhost:11434",
            api_host="localhost",
        )
        result = validate_all_settings(settings)
        assert len(result) == 1
        assert "Invalid URL" in result[0]


class TestCheckAndWarn:
    def test_check_and_warn_logs_violations(self):
        settings = MockSettings(
            database_url="postgresql://db.example.com:5432/synapse",
            ollama_url="http://localhost:11434",
            api_host="localhost",
        )

        with patch("src.local_only.log") as mock_log:
            result = check_and_warn(settings)
            assert len(result) == 1
            mock_log.warning.assert_called_once()
            args = mock_log.warning.call_args[0]
            assert "LOCAL-ONLY VIOLATION" in args[0]
            assert "db.example.com" in args[1]

    def test_check_and_warn_no_violations_no_log(self):
        settings = MockSettings(
            database_url="postgresql://localhost:5432/synapse",
            ollama_url="http://localhost:11434",
            api_host="localhost",
        )

        with patch("src.local_only.log") as mock_log:
            result = check_and_warn(settings)
            assert result == []
            mock_log.warning.assert_not_called()
