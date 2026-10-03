"""Tests for config — Settings dataclass with YAML loading and reload."""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.config import Settings, DEFAULT_CONFIG_PATH


class TestSettingsDefaults:
    def test_default_values(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("SYNAPSE_DB_URL", raising=False)
        monkeypatch.delenv("OLLAMA_URL", raising=False)
        monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
        monkeypatch.delenv("EMBEDDING_DIM", raising=False)
        monkeypatch.delenv("EMBEDDING_TIMEOUT", raising=False)
        monkeypatch.delenv("SYNAPSE_HOST", raising=False)
        monkeypatch.delenv("SYNAPSE_PORT", raising=False)
        monkeypatch.delenv("SYNAPSE_LOG_LEVEL", raising=False)
        monkeypatch.delenv("SEARCH_WEIGHTS", raising=False)
        monkeypatch.delenv("CACHE_TTL", raising=False)
        monkeypatch.delenv("CACHE_MAX_SIZE", raising=False)
        monkeypatch.delenv("SYNAPSE_PID_FILE", raising=False)
        monkeypatch.delenv("SYNAPSE_SCAN_INTERVAL", raising=False)
        monkeypatch.delenv("SYNAPSE_RECONCILE_HOUR", raising=False)
        monkeypatch.delenv("SYNAPSE_CONFIG", raising=False)
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
        monkeypatch.delenv("SYNAPSE_TOPIC_INTERVAL", raising=False)
        monkeypatch.delenv("SYNAPSE_WEBHOOK_SECRET", raising=False)
        monkeypatch.delenv("LINE_CHANNEL_SECRET", raising=False)
        monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
        monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
        monkeypatch.delenv("OPENROUTER_VISION_MODEL", raising=False)
        monkeypatch.delenv("OPENROUTER_SUMMARY_MODEL", raising=False)
        monkeypatch.delenv("OPENROUTER_TIMEOUT", raising=False)

        settings = Settings()
        assert settings.ollama_url == "http://localhost:11434"
        assert settings.embedding_model == "nomic-embed-text"
        assert settings.embedding_dim == 768
        assert settings.embedding_timeout == 30
        assert settings.api_host == "0.0.0.0"
        assert settings.api_port == 8420
        assert settings.log_level == "INFO"
        assert settings.search_weights == [0.6, 0.4]
        assert settings.search_rrf_k == 60
        assert settings.cache_ttl == 300
        assert settings.cache_max_size == 1000
        assert settings.scan_interval == 0
        assert settings.reconcile_hour == 2
        assert settings.config_path == ""
        assert settings.serper_api_key == ""
        assert settings.tavily_api_key == ""
        assert settings.web_search_provider == "serper"
        assert settings.topic_monitor_interval == 3600
        assert settings.webhook_secret == ""
        assert settings.line_channel_secret == ""
        assert settings.line_channel_access_token == ""
        assert settings.openrouter_api_key == ""
        assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"
        assert settings.openrouter_model == "google/gemini-2.0-flash-001"
        assert settings.openrouter_vision_model == "google/gemini-2.0-flash-001"
        assert settings.openrouter_summary_model == "deepseek/deepseek-chat-v3-0324"
        assert settings.openrouter_timeout == 60

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_URL", "http://custom:11434")
        monkeypatch.setenv("SYNAPSE_PORT", "9000")
        monkeypatch.setenv("EMBEDDING_DIM", "512")
        monkeypatch.setenv("CACHE_TTL", "60")
        monkeypatch.setenv("OPENROUTER_MODEL", "custom/model")

        settings = Settings()
        assert settings.ollama_url == "http://custom:11434"
        assert settings.api_port == 9000
        assert settings.embedding_dim == 512
        assert settings.cache_ttl == 60
        assert settings.openrouter_model == "custom/model"

    def test_database_url_env_priority(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgres://env-url")
        monkeypatch.setenv("SYNAPSE_DB_URL", "postgres://synapse-url")
        settings = Settings()
        assert settings.database_url == "postgres://env-url"

    def test_database_url_synapse_fallback(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("SYNAPSE_DB_URL", "postgres://synapse-url")
        settings = Settings()
        assert settings.database_url == "postgres://synapse-url"

    def test_search_weights_parsing(self, monkeypatch):
        monkeypatch.setenv("SEARCH_WEIGHTS", "0.7,0.3")
        settings = Settings()
        assert settings.search_weights == [0.7, 0.3]


class TestSettingsFromYaml:
    def test_from_yaml_missing_file_returns_defaults(self, monkeypatch):
        settings = Settings.from_yaml("/nonexistent/config.yaml")
        assert settings.ollama_url == "http://localhost:11434"

    def test_from_yaml_loads_values(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SYNAPSE_PORT", raising=False)
        config = tmp_path / "config.yaml"
        config.write_text(
            "ollama_url: http://yaml-host:11434\napi_port: 7777\n", encoding="utf-8"
        )
        settings = Settings.from_yaml(str(config))
        assert settings.ollama_url == "http://yaml-host:11434"
        assert settings.api_port == 7777

    def test_from_yaml_ignores_unknown_keys(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text(
            "unknown_key: value\nollama_url: http://known:11434\n", encoding="utf-8"
        )
        settings = Settings.from_yaml(str(config))
        assert settings.ollama_url == "http://known:11434"
        assert not hasattr(settings, "unknown_key")

    def test_from_yaml_ignores_none_values(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text(
            "ollama_url: null\napi_port: 8888\n", encoding="utf-8"
        )
        settings = Settings.from_yaml(str(config))
        assert settings.ollama_url == "http://localhost:11434"  # default
        assert settings.api_port == 8888

    def test_from_yaml_empty_file(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("", encoding="utf-8")
        settings = Settings.from_yaml(str(config))
        assert isinstance(settings, Settings)

    def test_from_yaml_uses_default_path(self, monkeypatch):
        checked_paths = []

        def mock_exists(self):
            checked_paths.append(str(self))
            return False

        monkeypatch.setattr(Path, "exists", mock_exists)
        Settings.from_yaml(None)
        assert str(DEFAULT_CONFIG_PATH) in checked_paths

    def test_from_yaml_import_error(self, tmp_path, monkeypatch):
        config = tmp_path / "config.yaml"
        config.write_text("ollama_url: http://yaml:11434\n", encoding="utf-8")
        monkeypatch.setattr(
            "builtins.__import__",
            lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError()) if name == "yaml" else __import__(name, *args, **kwargs),
        )
        settings = Settings.from_yaml(str(config))
        assert settings.ollama_url == "http://localhost:11434"

    def test_from_yaml_exception_handling(self, tmp_path, monkeypatch):
        config = tmp_path / "config.yaml"
        config.write_text("ollama_url: http://yaml:11434\n", encoding="utf-8")
        monkeypatch.setattr("builtins.open", MagicMock(side_effect=OSError("read error")))
        settings = Settings.from_yaml(str(config))
        assert isinstance(settings, Settings)


class TestSettingsReload:
    def test_reload_updates_values(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SYNAPSE_PORT", raising=False)
        config = tmp_path / "config.yaml"
        config.write_text(
            "ollama_url: http://reloaded:11434\napi_port: 9999\n", encoding="utf-8"
        )
        monkeypatch.setenv("SYNAPSE_CONFIG", str(config))

        settings = Settings()
        assert settings.ollama_url == "http://localhost:11434"
        assert settings.api_port == 8420

        settings.reload()
        assert settings.ollama_url == "http://reloaded:11434"
        assert settings.api_port == 9999

    def test_reload_preserves_config_path(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SYNAPSE_CONFIG", raising=False)
        config = tmp_path / "config.yaml"
        config.write_text("api_port: 1111\n", encoding="utf-8")

        settings = Settings()
        settings.config_path = str(config)
        settings.reload()
        assert settings.config_path == str(config)
        assert settings.api_port == 1111
