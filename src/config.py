"""Configuration — settings from environment variables + optional YAML config."""

import os
from dataclasses import dataclass, field
from pathlib import Path

import logging

log = logging.getLogger("synapse.config")

DEFAULT_CONFIG_PATH = Path.home() / ".synapse" / "config.yaml"


@dataclass
class Settings:
    # SYNAPSE_DB_URL takes precedence: DATABASE_URL is a generic name many
    # projects export, and a leaked one (e.g. from another project's .env)
    # silently points us at a DB without pgvector. Dedicated var wins.
    database_url: str = field(default_factory=lambda: os.getenv(
        "SYNAPSE_DB_URL",
        os.getenv("DATABASE_URL", "postgresql://admin:88888888@localhost:5432/synapse")
    ))
    ollama_url: str = field(default_factory=lambda: os.getenv(
        "OLLAMA_URL", "http://localhost:11434"
    ))
    embedding_model: str = field(default_factory=lambda: os.getenv(
        "EMBEDDING_MODEL", "nomic-embed-text"
    ))
    embedding_dim: int = field(default_factory=lambda: int(os.getenv(
        "EMBEDDING_DIM", "768"
    )))
    embedding_timeout: int = field(default_factory=lambda: int(os.getenv(
        "EMBEDDING_TIMEOUT", "30"
    )))
    api_host: str = field(default_factory=lambda: os.getenv(
        "SYNAPSE_HOST", "0.0.0.0"
    ))
    api_port: int = field(default_factory=lambda: int(os.getenv(
        "SYNAPSE_PORT", "8420"
    )))
    log_level: str = field(default_factory=lambda: os.getenv(
        "SYNAPSE_LOG_LEVEL", "INFO"
    ))
    search_weights: list[float] = field(default_factory=lambda: [
        float(x) for x in os.getenv("SEARCH_WEIGHTS", "0.6,0.4").split(",")
    ])
    search_rrf_k: int = 60
    cache_ttl: int = field(default_factory=lambda: int(os.getenv(
        "CACHE_TTL", "300"
    )))
    cache_max_size: int = field(default_factory=lambda: int(os.getenv(
        "CACHE_MAX_SIZE", "1000"
    )))
    # Daemon settings
    daemon_pid_file: str = field(default_factory=lambda: os.getenv(
        "SYNAPSE_PID_FILE", str(Path.home() / ".synapse" / "synapse.pid")
    ))
    scan_interval: int = field(default_factory=lambda: int(os.getenv(
        "SYNAPSE_SCAN_INTERVAL", "0"
    )))  # 0 = disabled
    reconcile_hour: int = field(default_factory=lambda: int(os.getenv(
        "SYNAPSE_RECONCILE_HOUR", "2"
    )))  # 0-23, default 2 AM
    config_path: str = field(default_factory=lambda: os.getenv(
        "SYNAPSE_CONFIG", ""
    ))
    # Web search API keys
    serper_api_key: str = field(default_factory=lambda: os.getenv(
        "SERPER_API_KEY", ""
    ))
    tavily_api_key: str = field(default_factory=lambda: os.getenv(
        "TAVILY_API_KEY", ""
    ))
    web_search_provider: str = field(default_factory=lambda: os.getenv(
        "WEB_SEARCH_PROVIDER", "serper"
    ))
    obsidian_vault_path: str = field(default_factory=lambda: os.getenv(
        "OBSIDIAN_VAULT_PATH", ""
    ))
    topic_monitor_interval: int = field(default_factory=lambda: int(os.getenv(
        "SYNAPSE_TOPIC_INTERVAL", "3600"
    )))  # 0 = disabled, default 1 hour
    # Webhook security
    webhook_secret: str = field(default_factory=lambda: os.getenv(
        "SYNAPSE_WEBHOOK_SECRET", ""
    ))  # empty = no signature verification
    # LINE integration
    line_channel_secret: str = field(default_factory=lambda: os.getenv(
        "LINE_CHANNEL_SECRET", ""
    ))  # LINE webhook signature verification
    line_channel_access_token: str = field(default_factory=lambda: os.getenv(
        "LINE_CHANNEL_ACCESS_TOKEN", ""
    ))  # Optional — for reply messages
    # OpenRouter LLM integration (fallback to Ollama)
    openrouter_api_key: str = field(default_factory=lambda: os.getenv(
        "OPENROUTER_API_KEY", ""
    ))
    openrouter_base_url: str = field(default_factory=lambda: os.getenv(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    ))
    openrouter_model: str = field(default_factory=lambda: os.getenv(
        "OPENROUTER_MODEL", "google/gemini-2.0-flash-001"
    ))  # default: cheap + Thai-capable
    openrouter_vision_model: str = field(default_factory=lambda: os.getenv(
        "OPENROUTER_VISION_MODEL", "google/gemini-2.0-flash-001"
    ))
    openrouter_summary_model: str = field(default_factory=lambda: os.getenv(
        "OPENROUTER_SUMMARY_MODEL", "deepseek/deepseek-chat-v3-0324"
    ))
    openrouter_timeout: int = field(default_factory=lambda: int(os.getenv(
        "OPENROUTER_TIMEOUT", "60"
    )))

    @classmethod
    def from_yaml(cls, path: str | Path | None = None) -> "Settings":
        """Load settings from YAML file, falling back to env vars for missing keys."""
        if path is None:
            path = DEFAULT_CONFIG_PATH
        path = Path(path)

        settings = cls()

        if not path.exists():
            return settings

        try:
            import yaml
            with open(path, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}

            for key, value in config.items():
                if hasattr(settings, key) and value is not None:
                    setattr(settings, key, value)

            log.info("Loaded config from %s", path)
        except ImportError:
            log.warning("PyYAML not installed, skipping config file")
        except Exception as e:
            log.warning("Failed to load config from %s: %s", path, e)

        return settings

    def reload(self) -> None:
        """Re-read settings from env vars + config file (for SIGHUP)."""
        new_settings = Settings.from_yaml(self.config_path or None)
        for key in vars(new_settings):
            if key != "config_path":
                setattr(self, key, getattr(new_settings, key))
        log.info("Configuration reloaded")