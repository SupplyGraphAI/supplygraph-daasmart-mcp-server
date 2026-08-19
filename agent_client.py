#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP client for the Agent API over public HTTP."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import Settings

logger = logging.getLogger("mcp_sdk_server")

MCP_RUN_TEXT_MARKER = "from_mcp"
INVOKE_VIA_MCP = "mcp"
MODE_RUN = "run"
MODE_STATUS = "status"
MODE_RESULTS = "results"


class AgentHttpError(Exception):
    def __init__(self, message: str, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class AgentClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    def _headers(self, authorization: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Original-Host": self._settings.mcp_public_host,
        }
        if authorization:
            headers["Authorization"] = authorization
        return headers

    async def _request(
        self,
        method: str,
        url: str,
        *,
        authorization: str | None = None,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        try:
            response = await self._http.request(
                method,
                url,
                headers=self._headers(authorization),
                json=json_body,
                params=params,
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            logger.warning("agent HTTP request failed: %s", exc)
            raise AgentHttpError("Agent HTTP request failed") from exc

        if response.status_code == 401:
            raise AgentHttpError("Unauthorized", status_code=401, body=_safe_json(response))
        if response.status_code == 404:
            raise AgentHttpError("Agent not found", status_code=404, body=_safe_json(response))
        if response.status_code >= 400:
            logger.warning("agent HTTP %s", response.status_code)
            raise AgentHttpError(
                "Agent request failed",
                status_code=response.status_code,
                body=_safe_json(response),
            )
        return _safe_json(response)

    async def list_agents(self) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            self._settings.agent_base_url,
            params={"mcp": "1", "status": "active"},
        )
        agents = payload.get("agents") if isinstance(payload, dict) else None
        if not isinstance(agents, list):
            return []
        return [item for item in agents if isinstance(item, dict)]

    async def get_manifest(self, agent_id: str) -> dict[str, Any]:
        url = "{}/{}/manifest".format(self._settings.agent_base_url, agent_id)
        payload = await self._request("GET", url)
        return payload if isinstance(payload, dict) else {}

    async def run(
        self,
        agent_id: str,
        authorization: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        url = "{}/{}/run".format(self._settings.agent_base_url, agent_id)
        body = {
            "mode": MODE_RUN,
            "text": MCP_RUN_TEXT_MARKER,
            "invoke_via": INVOKE_VIA_MCP,
            "from_mcp": dict(arguments or {}),
            "stream": False,
        }
        payload = await self._request(
            "POST",
            url,
            authorization=authorization,
            json_body=body,
            timeout=min(60.0, float(self._settings.sync_call_timeout_seconds)),
        )
        return payload if isinstance(payload, dict) else {}

    async def status(
        self,
        agent_id: str,
        authorization: str,
        task_id: str,
    ) -> dict[str, Any]:
        url = "{}/{}/run".format(self._settings.agent_base_url, agent_id)
        payload = await self._request(
            "POST",
            url,
            authorization=authorization,
            json_body={"mode": MODE_STATUS, "task_id": task_id, "stream": False},
            timeout=30.0,
        )
        return payload if isinstance(payload, dict) else {}

    async def results(
        self,
        agent_id: str,
        authorization: str,
        task_id: str,
    ) -> dict[str, Any]:
        url = "{}/{}/run".format(self._settings.agent_base_url, agent_id)
        payload = await self._request(
            "POST",
            url,
            authorization=authorization,
            json_body={
                "mode": MODE_RESULTS,
                "task_id": task_id,
                "invoke_via": INVOKE_VIA_MCP,
                "stream": False,
            },
            timeout=60.0,
        )
        return payload if isinstance(payload, dict) else {}


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}
