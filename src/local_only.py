"""Local-only enforcement — validate all service URLs are localhost."""

import logging
from urllib.parse import urlparse

log = logging.getLogger("synapse.local_only")

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}

# Docker-allowed: 0.0.0.0 only when SYNAPSE_ALLOW_EXTERNAL=1


def validate_local_url(url: str, allow_docker: bool = False) -> list[str]:
    """Validate that a URL points to localhost only. Returns list of violations."""
    violations = []
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""

        # Unix socket paths (no hostname)
        if not hostname:
            return violations

        if hostname in LOCAL_HOSTS:
            return violations

        # Allow .internal TLD for Docker
        if allow_docker and (hostname.endswith(".internal") or hostname == "host.docker.internal"):
            return violations

        violations.append(f"Non-localhost URL: {url} (hostname={hostname})")
    except Exception as e:
        violations.append(f"Invalid URL: {url} ({e})")

    return violations


def validate_all_settings(settings, allow_docker: bool = False) -> list[str]:
    """Validate all service URLs in settings are localhost. Returns list of violations."""
    violations = []

    for url_name, url_value in [
        ("database_url", settings.database_url),
        ("ollama_url", settings.ollama_url),
    ]:
        violations.extend(validate_local_url(url_value, allow_docker=allow_docker))

    # Check api_host
    api_host = settings.api_host
    if api_host not in LOCAL_HOSTS and not (allow_docker and api_host == "0.0.0.0"):
        violations.append(f"Non-localhost api_host: {api_host}")

    return violations


def check_and_warn(settings, allow_docker: bool = False) -> list[str]:
    """Validate settings and log warnings for violations. Returns list of violations."""
    violations = validate_all_settings(settings, allow_docker=allow_docker)
    for v in violations:
        log.warning("LOCAL-ONLY VIOLATION: %s", v)
    return violations