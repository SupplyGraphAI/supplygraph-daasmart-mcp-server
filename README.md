# SupplyGraph.AI Data MCP Server

This is the **data-access MCP server** for [SupplyGraph.AI](https://supplygraph.ai).

Clients call tools to **fetch data** from SupplyGraph. What you can fetch is listed below. This repository is the source of the hosted endpoint for China-region access. Hostnames under `daasmart.com` are only used to **register for an API key** and to **send MCP requests**; they are not a separate product.

| Role | URL |
|------|------|
| Public MCP | `https://mcp.daasmart.com/mcp` |
| Upstream Agent API | `https://agent.daasmart.com/api/v1/agents` |
| Console (API keys) | https://www.daasmart.com/zk_chat_os/dashboard/dashboard.html |

## What this MCP is for

This is a **read-only data MCP** for SupplyGraph.AI. Clients list tools with `tools/list` and fetch data with `tools/call`. It does not write to the graph, does not require uploading supplier lists, and does not store user credentials.

Tools query **places, regions, parks, industries, and companies** on SupplyGraph’s continuously updated data. Typical questions: which firms sit in a park, how a city/district is doing, who is in a named industry chain, or what is around a specific address.

Live tool names and input schemas come from `tools/list`. Use that list; do not hard-code agent ids.

### What you can query

| Scope | English | You ask about | You get | Not for |
|------|---------|----------------|---------|---------|
| **选点** | POI | A named, map-located facility in an administrative area (school, hospital, gas station, bank/ATM, pharmacy, restaurant, brand outlet) | The matching places (names/locations), not a count | “How many schools in this city?” |
| **园区** | Park | A named industrial park or development zone | Enterprises and attributes of that park | An unnamed city-wide firm dump |
| **区域** | Region | A province / city / district | Aggregate indicators and trends: population, GDP, fiscal, investment, employment, land, housing, traffic, public services | Name-level company lists |
| **产业** | Industry | A named industry chain (e.g. NEV, low-altitude economy, ICs), optionally scoped by region | Enterprise lists or counts under that chain | A chain name you do not have |
| **企业** | Company | One known firm (name or USCC), **or** a filter by region + registration conditions (capital, industry, status, abnormal operations, dishonesty, listing, social-insurance headcount, founding year, keywords) | A single-firm profile, or a filtered firm set — no park/chain name required | |
| **地址周边** | Address nearby | A specific address, landmark, road, community, or park gate | Nearby population, housing prices, facilities, and similar indicators | The same metrics for an admin region alone (use **Region**) |

The same server also exposes supply-chain tools (risk prediction, enterprise-change monitoring, tariff/HS) when those agents are `mcp.enabled`. Prefer the table above for China geo and registry questions.

### How to choose a tool

- Named facility on a map → **POI / 选点**
- Named park or zone → **Park / 园区**
- Province / city / district totals or trends → **Region / 区域**
- Named industry chain → **Industry / 产业**
- One company, or firms matching registration filters → **Company / 企业**
- Around a street address or landmark → **Address nearby / 地址周边**

## Connect

Hosted endpoint: `https://mcp.daasmart.com/mcp`  
Transport: MCP Streamable HTTP.

### 1. Get an API key

1. Open the [SupplyGraph.AI Console](https://www.daasmart.com/zk_chat_os/dashboard/dashboard.html). If you are not signed in, you will be redirected to the login page. New users can register there.
2. After you sign in, you land on the Console. Open **A2A / MCP** and click **Create Production Key** or **Create Sandbox Key**.
3. Copy the key and keep it private. Use it as `Authorization: Bearer <api_key>`.

The same SupplyGraph.AI key works for MCP, A2A, and the Agent API.  
Sandbox keys (no credit consumption) are also created in that Console page.  
Account, billing, and key management stay in the Console — this repository does not issue keys.

### 2. Add the server to an MCP client

```json
{
  "mcpServers": {
    "supplygraph": {
      "url": "https://mcp.daasmart.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

Replace `YOUR_API_KEY` with the raw key from the Console. If your client config already prefixes `Bearer ` (for example Cursor `.mcp.json` with `"Authorization": "Bearer ${env:SUPPLYGRAPH_API_KEY}"`), put only the raw key in the variable — do not add a second `Bearer`.

`tools/call` requires the Bearer token. `initialize` and `tools/list` do not.

## How this server works (adapter)

A small adapter process:

1. Speaks standard MCP (Streamable HTTP) using the official Python SDK (`mcp`).
2. Lists SupplyGraph.AI agents as MCP tools (`tools/list`).
3. On `tools/call`, forwards the request to the Agent HTTP API and returns the result.

It does not contain business-agent logic, a database, or stored user credentials.  
API keys are supplied by the MCP client as `Authorization: Bearer <api_key>` and forwarded to the Agent API.

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

Environment variables are listed in `.env.example`. Defaults already point at the China-region SupplyGraph.AI hosts (`mcp.daasmart.com` and `agent.daasmart.com`).

## Security notes for review

- No secrets are hardcoded. Keys come from the client request header.
- `.env` is local-only and is gitignored; `.env.example` has no credentials.
- This process only calls the documented Agent HTTPS API.
- Failed Agent HTTP calls are logged server-side; raw upstream bodies are not returned to MCP clients.

## License

MIT. See `LICENSE`.
