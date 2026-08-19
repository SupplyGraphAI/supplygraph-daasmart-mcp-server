# SupplyGraph.AI MCP Server

Official MCP server for [SupplyGraph.AI](https://supplygraph.ai).

This repository is the source of the hosted MCP endpoint. The product brand is **SupplyGraph.AI**.  
`daasmart.com` is a market-specific hostname for the same product.

| Role | URL |
|------|------|
| Public MCP | `https://mcp.daasmart.com/mcp` |
| Upstream Agent API | `https://agent.daasmart.com/api/v1/agents` |

## What this server does

A small adapter process:

1. Speaks standard MCP (Streamable HTTP) using the official Python SDK (`mcp`).
2. Lists SupplyGraph.AI agents as MCP tools (`tools/list`).
3. On `tools/call`, forwards the request to the Agent HTTP API and returns the result.

It does not contain business-agent logic, a database, or stored user credentials.  
API keys are supplied by the MCP client as `Authorization: Bearer <api_key>` and forwarded to the Agent API.

## Endpoints

| Path | Purpose |
|------|---------|
| `POST/GET /mcp` | MCP Streamable HTTP (public URL: `https://mcp.daasmart.com/mcp`) |
| `GET /health` | Liveness check for operators |

`tools/call` requires:

```
Authorization: Bearer <api_key>
```

`tools/list` and `initialize` do not require a key.

## Run locally (for review)

Requires Python 3.11.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
python server.py
```

Windows:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
python server.py
```

Default listen address: `0.0.0.0:8080`

- MCP: `http://127.0.0.1:8080/mcp`
- Health: `http://127.0.0.1:8080/health`

Point an MCP Inspector or client at `http://127.0.0.1:8080/mcp`.  
Production traffic is reverse-proxied from `https://mcp.daasmart.com/mcp`.

## Adapter behavior

- `tools/list` → `GET https://agent.daasmart.com/api/v1/agents?mcp=1`  
  Only agents with `mcp.enabled=true` are exposed as tools.
- `tools/call` → `POST https://agent.daasmart.com/api/v1/agents/{agent_id}/run`  
  The MCP arguments are sent as Agent input. The server waits for a terminal status (timeout configurable, default 600s) and returns a standard MCP `CallToolResult`.

Environment variables are listed in `.env.example`. Defaults already point at `mcp.daasmart.com` and `agent.daasmart.com`.

## Security notes for review

- No secrets are hardcoded. Keys come from the client request header.
- `.env` is local-only and is gitignored; `.env.example` has no credentials.
- This process only calls the documented Agent HTTPS API.
- Failed Agent HTTP calls are logged server-side; raw upstream bodies are not returned to MCP clients.

## License

MIT. See `LICENSE`.
