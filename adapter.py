#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP ↔ Agent adapter: discovery as tools, tools/call → /run + poll."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from copy import deepcopy
from typing import Any

import mcp.types as types

from agent_client import AgentClient, AgentHttpError
from config import Settings

try:
    ToolAnnotations = types.ToolAnnotations
except AttributeError:  # pragma: no cover
    ToolAnnotations = None

logger = logging.getLogger("mcp_sdk_server")

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

CODE_TO_STATUS = {
    "TASK_ACCEPTED": "working",
    "TASK_RUNNING": "working",
    "INTERPRETING": "working",
    "WAITING_USER": "input_required",
    "TASK_COMPLETED": "completed",
    "TASK_FAILED": "failed",
    "TASK_CANCELLED": "cancelled",
    "INVALID_REQUEST": "failed",
    "UNAUTHORIZED": "failed",
    "INSUFFICIENT_CREDITS": "failed",
}
TERMINAL = frozenset({"completed", "failed", "cancelled", "input_required"})


class AdapterError(Exception):
    def __init__(self, message: str, *, unauthorized: bool = False):
        super().__init__(message)
        self.unauthorized = unauthorized


class AgentAdapter:
    def __init__(self, settings: Settings, client: AgentClient):
        self._settings = settings
        self._client = client
        self._tools: dict[str, types.Tool] = {}
        self._agents: dict[str, dict[str, Any]] = {}
        self._loaded_at = 0.0

    def _cache_fresh(self) -> bool:
        if self._loaded_at <= 0:
            return False
        return (time.monotonic() - self._loaded_at) < float(
            self._settings.tools_cache_ttl_seconds
        )

    async def refresh_tools(self, force: bool = False) -> int:
        if not force and self._cache_fresh():
            return len(self._tools)
        agents = await self._client.list_agents()
        tools: dict[str, types.Tool] = {}
        stored: dict[str, dict[str, Any]] = {}
        for agent in agents:
            if not is_mcp_exposed(agent):
                continue
            agent_id = str(agent.get("agent_id") or "")
            if not agent_id:
                continue
            tool = build_mcp_tool(agent)
            tools[agent_id] = tool
            stored[agent_id] = agent
        self._tools = tools
        self._agents = stored
        self._loaded_at = time.monotonic()
        logger.info("refreshed MCP tools: %s from %s", len(tools), self._settings.agent_base_url)
        return len(tools)

    async def list_tools(self) -> list[types.Tool]:
        await self.refresh_tools()
        return list(self._tools.values())

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        authorization: str | None,
    ) -> list[types.ContentBlock]:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise AdapterError("Authorization Bearer token is required", unauthorized=True)

        await self.refresh_tools()
        tool = self._tools.get(name)
        if tool is None:
            raise AdapterError("Unknown tool: {}".format(name))

        arguments = arguments or {}
        if not isinstance(arguments, dict):
            raise AdapterError("arguments must be an object")
        validate_arguments(tool, arguments)

        try:
            run_resp = await self._client.run(name, authorization, arguments)
        except AgentHttpError as exc:
            if exc.status_code == 401:
                raise AdapterError("Unauthorized", unauthorized=True) from exc
            raise AdapterError(str(exc)) from exc

        task_id = extract_task_id(run_resp)
        if not task_id:
            raise AdapterError("Agent did not return task_id")

        deadline = time.monotonic() + float(self._settings.sync_call_timeout_seconds)
        last_status_resp = run_resp
        while time.monotonic() < deadline:
            status = agent_status(last_status_resp)
            if status in TERMINAL:
                return await self._finish(name, authorization, task_id, last_status_resp, status)
            await asyncio.sleep(self._settings.poll_interval_seconds)
            try:
                last_status_resp = await self._client.status(name, authorization, task_id)
            except AgentHttpError as exc:
                if exc.status_code == 401:
                    raise AdapterError("Unauthorized", unauthorized=True) from exc
                raise AdapterError(str(exc)) from exc

        raise AdapterError(
            "Task timed out after {} seconds (task_id={})".format(
                int(self._settings.sync_call_timeout_seconds),
                task_id,
            )
        )

    async def _finish(
        self,
        agent_id: str,
        authorization: str,
        task_id: str,
        status_resp: dict[str, Any],
        status: str,
    ) -> list[types.ContentBlock]:
        if status == "completed":
            try:
                results_resp = await self._client.results(agent_id, authorization, task_id)
            except AgentHttpError as exc:
                raise AdapterError(str(exc)) from exc
            content = extract_content(results_resp)
            return [types.TextContent(type="text", text=content_to_text(content))]

        message = extract_message(status_resp) or status
        if status_resp.get("code") == "INSUFFICIENT_CREDITS":
            topup = (status_resp.get("metadata") or {}).get("credits_topup_url")
            if topup:
                message = "{} credits_topup_url={}".format(message, topup)
        raise AdapterError(message)


def is_mcp_exposed(agent: dict[str, Any]) -> bool:
    mcp_cfg = agent.get("mcp")
    if isinstance(mcp_cfg, str):
        try:
            mcp_cfg = json.loads(mcp_cfg)
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
    if not isinstance(mcp_cfg, dict) or not mcp_cfg:
        return False
    return mcp_cfg.get("enabled") is True


def build_mcp_tool(agent: dict[str, Any]) -> types.Tool:
    agent_id = str(agent.get("agent_id") or "")
    mcp_cfg = agent.get("mcp") or {}
    if isinstance(mcp_cfg, str):
        try:
            mcp_cfg = json.loads(mcp_cfg)
        except (TypeError, ValueError, json.JSONDecodeError):
            mcp_cfg = {}
    if not isinstance(mcp_cfg, dict):
        mcp_cfg = {}

    input_schema = mcp_cfg.get("input_schema") or {"type": "object", "properties": {}}
    if not isinstance(input_schema, dict):
        input_schema = {"type": "object", "properties": {}}

    description = str(agent.get("description") or agent.get("name") or agent_id)
    pricing = agent.get("pricing")
    if isinstance(pricing, dict) and pricing:
        description = "{}\n\nPricing: {}".format(description, pricing)

    output_schema = agent.get("output_schema")
    if not isinstance(output_schema, dict):
        manifest = agent.get("manifest") or {}
        if isinstance(manifest, dict):
            output_schema = manifest.get("output_schema")
    if not isinstance(output_schema, dict):
        output_schema = None

    kwargs: dict[str, Any] = {
        "name": agent_id,
        "description": description,
        "inputSchema": deepcopy(input_schema),
    }
    title = str(agent.get("name") or agent_id)
    extra: dict[str, Any] = {}
    if ToolAnnotations is not None:
        extra["annotations"] = ToolAnnotations(openWorldHint=True)
    extra["title"] = title
    if output_schema:
        extra["outputSchema"] = deepcopy(output_schema)
    try:
        return types.Tool(**extra, **kwargs)
    except TypeError:
        extra.pop("outputSchema", None)
        try:
            return types.Tool(**extra, **kwargs)
        except TypeError:
            extra.pop("annotations", None)
            extra.pop("title", None)
            return types.Tool(**extra, **kwargs)


def validate_arguments(tool: types.Tool, arguments: dict[str, Any]) -> None:
    schema = tool.inputSchema or {}
    if not isinstance(schema, dict) or not schema:
        return
    if jsonschema is not None:
        try:
            jsonschema.validate(instance=arguments, schema=schema)
        except jsonschema.ValidationError as exc:
            raise AdapterError("Input validation error: {}".format(exc.message)) from exc
        return
    for field_name in schema.get("required") or []:
        if field_name not in arguments:
            raise AdapterError(
                "Input validation error: '{}' is a required property".format(field_name)
            )


def extract_task_id(resp: dict[str, Any]) -> str:
    data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    return str(data.get("task_id") or resp.get("task_id") or "")


def agent_status(resp: dict[str, Any]) -> str:
    data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    code = resp.get("code") or data.get("code")
    if code in CODE_TO_STATUS:
        return CODE_TO_STATUS[code]
    stage = data.get("stage")
    if stage == "completed":
        return "completed"
    if stage == "cancelled":
        return "cancelled"
    if stage in ("executing", "interpreting"):
        return "working"
    return "working"


def extract_message(resp: dict[str, Any]) -> str | None:
    data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    content = data.get("content")
    if content is None or content == "":
        message = resp.get("message")
        return str(message) if message else None
    return content_to_text(content)


def extract_content(resp: dict[str, Any]) -> Any:
    data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    if "content" in data:
        return data.get("content")
    return data or resp.get("message")


def content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, (dict, list)):
        return json.dumps(content, ensure_ascii=False)
    return str(content)
