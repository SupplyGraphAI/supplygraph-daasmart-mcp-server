#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Environment-only settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    path = Path(__file__).resolve().parent / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    return int(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"

    # Public MCP endpoint for this market: https://mcp.daasmart.com/mcp
    mcp_public_url: str = "https://mcp.daasmart.com/mcp"
    mcp_public_host: str = "mcp.daasmart.com"

    # Upstream Agent API for this market: https://agent.daasmart.com/api/v1/agents
    agent_base_url: str = "https://agent.daasmart.com/api/v1/agents"

    tools_cache_ttl_seconds: int = 300
    sync_call_timeout_seconds: int = 600
    poll_interval_seconds: float = 5.0
    json_response: bool = False
    stateless_http: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        return cls(
            host=_env("MCP_HOST", "0.0.0.0"),
            port=_env_int("MCP_PORT", 8080),
            log_level=_env("MCP_LOG_LEVEL", "INFO") or "INFO",
            mcp_public_url=_env(
                "MCP_PUBLIC_URL", "https://mcp.daasmart.com/mcp"
            ).rstrip("/"),
            mcp_public_host=_env("MCP_PUBLIC_HOST", "mcp.daasmart.com"),
            agent_base_url=_env(
                "AGENT_BASE_URL", "https://agent.daasmart.com/api/v1/agents"
            ).rstrip("/"),
            tools_cache_ttl_seconds=_env_int("MCP_TOOLS_CACHE_TTL_SECONDS", 300),
            sync_call_timeout_seconds=_env_int("MCP_SYNC_CALL_TIMEOUT_SECONDS", 600),
            poll_interval_seconds=float(_env("MCP_POLL_INTERVAL_SECONDS") or 5.0),
            json_response=_env_bool("MCP_JSON_RESPONSE", False),
            stateless_http=_env_bool("MCP_STATELESS_HTTP", True),
        )
