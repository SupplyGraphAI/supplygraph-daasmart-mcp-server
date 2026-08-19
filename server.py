#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SupplyGraph.AI MCP Server (official MCP Python SDK).

Public MCP:   https://mcp.daasmart.com/mcp
Agent API:    https://agent.daasmart.com/api/v1/agents
"""

from __future__ import annotations

import contextlib
import inspect
import logging
from collections.abc import AsyncIterator
from contextvars import ContextVar
from typing import Any

import mcp.types as types
import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData, INTERNAL_ERROR, INVALID_PARAMS
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from adapter import AdapterError, AgentAdapter
from agent_client import AgentClient
from config import Settings

logger = logging.getLogger("mcp_sdk_server")

_authorization: ContextVar[str | None] = ContextVar("mcp_authorization", default=None)

UNAUTHORIZED = -32001


class AuthorizationMiddleware:
    """Capture Authorization from the HTTP request for tools/call forwarding."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") == "http":
            header_value = None
            for key, value in scope.get("headers") or []:
                if key.decode("latin-1").lower() == "authorization":
                    header_value = value.decode("latin-1")
                    break
            token = _authorization.set(header_value)
            try:
                await self.app(scope, receive, send)
            finally:
                _authorization.reset(token)
            return
        await self.app(scope, receive, send)


def create_mcp_server(adapter: AgentAdapter) -> Server:
    server = Server("SupplyGraph AI MCP Server")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return await adapter.list_tools()

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        try:
            return await adapter.call_tool(name, arguments or {}, _authorization.get())
        except AdapterError as exc:
            code = UNAUTHORIZED if exc.unauthorized else INVALID_PARAMS
            raise McpError(ErrorData(code=code, message=str(exc))) from exc
        except Exception as exc:
            logger.exception("tools/call failed name=%s", name)
            raise McpError(ErrorData(code=INTERNAL_ERROR, message="Internal error")) from exc

    return server


def create_app(settings: Settings | None = None) -> Starlette:
    settings = settings or Settings.from_env()
    client = AgentClient(settings)
    adapter = AgentAdapter(settings, client)
    mcp_server = create_mcp_server(adapter)

    session_kwargs: dict[str, Any] = {
        "app": mcp_server,
        "event_store": None,
        "json_response": settings.json_response,
    }
    manager_params = inspect.signature(StreamableHTTPSessionManager.__init__).parameters
    if "stateless" in manager_params:
        session_kwargs["stateless"] = settings.stateless_http
    session_manager = StreamableHTTPSessionManager(**session_kwargs)

    async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    async def health(_request: Request) -> JSONResponse:
        try:
            count = await adapter.refresh_tools()
            status = "ok"
        except Exception as exc:
            logger.warning("health tools refresh failed: %s", exc)
            count = 0
            status = "degraded"
        return JSONResponse(
            {
                "status": status,
                "service": "supplygraph-mcp-server",
                "tools": count,
            }
        )

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            try:
                await adapter.refresh_tools(force=True)
            except Exception as exc:
                logger.warning("startup tools refresh failed: %s", exc)
            logger.info(
                "MCP server ready public=%s agent=%s",
                settings.mcp_public_url,
                settings.agent_base_url,
            )
            try:
                yield
            finally:
                await client.aclose()

    starlette_app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Mount("/mcp", app=handle_mcp),
        ],
        lifespan=lifespan,
    )
    starlette_app = AuthorizationMiddleware(starlette_app)
    return CORSMiddleware(
        starlette_app,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id"],
    )


def main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
