# NCGR Agentic AI Copilot

A multi-agent AI assistant for the National Center for Government Resources
Systems (NCGR), Saudi Arabia — demonstrating **SAS agentic AI with a
customer-owned LLM**. The same UI as the NCGR RAM assistant, but with **no
SAS Retrieval Agent Manager dependency**: the agents run in this app against
Anthropic Claude and talk to SAS through the **SAS Viya MCP toolset**
(vendored into this repo).

> **The story for NCGR:** SAS Copilot requires SAS-hosted LLMs. This app
> shows the alternative: RAM (or any agent host) + the SAS Viya MCP + the
> LLM of your choice — here Claude Sonnet 5, swappable for an on-prem model.
> The tool layer is identical to the `sas-mcp-server` MCP server, so
> everything demonstrated here transfers 1:1 to a RAM + MCP deployment.

## The four agents (dropdown in the UI)

| Agent | What it does | Backed by |
|---|---|---|
| **SAS Viya Copilot** | Explore the environment, query data, run SAS code, generate data, build models with AutoML, real-time scoring — orchestrating five specialist sub-agents (data steward, data engineer, model builder, insights & reporting, platform guide) | SAS Viya environment via the vendored Viya MCP toolset (`backend/sasviya/`) |
| **Investigation Assistant** | Alert triage for SAS Visual Investigator: work the queue, explain why alerts fired, gather entity networks, flag false positives, recommend actions | VI environment via `backend/sasvi/` (svi-alert + svi-datahub REST) |
| **Procurement Integrity Analyst** | A per-use-case agent: tenders, bids, suppliers, invoices & red-flag alerts for Saudi government entities, with ready models (supplier risk, bid-rigging screen, price anomaly) | Bundled synthetic dataset + models (`backend/usecase/`) — runs with zero external dependencies |
| **Global Intelligence** | What other countries/agencies are doing, emerging tech, news monitoring with cited sources | Tavily web search (`backend/websearch/`, vendored from `Web_Search`) |

Everything an agent does is visible: live activity while it works, and a full
tool/LLM trace per answer (the grid icon under each response). Charts the
agents emit (`render_chart`) render as interactive SVG cards. Sub-agent steps
show up in the trace as `specialist › tool`.

**Arabic mode:** the عربي / English button in the header flips the whole UI
to Arabic (RTL layout, Arabic labels, Arabic voice input) and tells the
agents to answer in Modern Standard Arabic — and back again. The choice is
remembered per browser.

## Architecture

```
frontend/  React + Vite + Tailwind (copied from Finance_RAM_UI, RAM plumbing removed)
backend/   FastAPI
  ├─ agents/      agent definitions + system prompts (registry.py, prompts.py)
  ├─ services/    the agentic loop (runner.py) + in-memory sessions (store.py)
  ├─ sasviya/     SAS Viya toolset  — vendored from sas-mcp-server (Apache-2.0)
  ├─ sasvi/       SAS Visual Investigator toolset (implements the SAS_VI_MCP roadmap)
  ├─ websearch/   Tavily tools      — vendored from Web_Search
  ├─ usecase/     bundled procurement-integrity data + models
  └─ toolset.py   shared tool registry + render_chart
```

* The LLM is **Claude Sonnet 5** (`MODEL` env var to change) driving a
  standard tool-use loop with streaming and prompt caching.
* The MCP servers are vendored **in-process** — same tool names, arguments,
  and behavior as `sas-mcp-server`, without MCP transport overhead, so the
  whole app ships as **one container**. Swapping back to real MCP servers
  (e.g. under RAM) is a wiring change, not a rewrite.
* Queries run async: `POST /api/query` → poll `GET /api/query/{id}` with the
  live trace at `GET /api/query/{id}/trace` (this avoids gateway timeouts on
  long agent runs — same pattern as the RAM UI).

## Deploying to Railway

1. Push this repo to GitHub and create a Railway service from it — the
   `Dockerfile` + `railway.json` are picked up automatically (two-stage
   build: Vite frontend → FastAPI container, healthcheck on `/api/health`).
2. Set the environment variables (Variables tab). **Required:**

   | Variable | Purpose |
   |---|---|
   | `ANTHROPIC_API_KEY` | The LLM. Only hard requirement to boot. |
   | `VIYA_ENDPOINT` + `VIYA_REFRESH_TOKEN` (or `VIYA_USERNAME`/`VIYA_PASSWORD`) | SAS Viya Copilot |
   | `VI_ENDPOINT` + `VI_USERNAME`/`VI_PASSWORD` + `VI_CLIENT_ID=sas.cli` (or `VI_REFRESH_TOKEN` for SSO identities) | Investigation Assistant |
   | `TAVILY_API_KEY` | Global Intelligence + the copilot's platform-guide specialist |

   Useful optional ones: `SSL_VERIFY=false` / `VI_SSL_VERIFY=false` for
   self-signed certs, `CLIENT_ID`/`VI_CLIENT_ID` (default `sas-mcp`),
   `LLM_EFFORT` (`low`/`medium`/`high`), `MODEL`. Full list with
   explanations: [`backend/.env.example`](backend/.env.example).

3. Agents whose environment isn't configured stay usable in the UI and reply
   with a clear "not configured" explanation — so a partial setup still demos
   cleanly (the Procurement Integrity Analyst always works; it needs nothing).

### Getting a Viya refresh token

Same as the MCP servers: register/use an OAuth client (default `sas-mcp`) and
run `examples/get_refresh_token.py` from the `sas-mcp-server` repo against
each environment (once for Viya, once for VI). Password grant works too for
non-SSO accounts.

## Local development

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in keys
uvicorn main:app --reload --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev            # http://localhost:5173, proxies /api to :8000
```

## Demo script ideas (NCGR)

* **SAS Viya Copilot** — "Brainstorm a driver-risk dataset for a demo,
  generate 5,000 rows, profile it, then build a model with AutoML and score
  one record." Watch the copilot delegate to the data engineer → data steward
  → model builder in the trace.
* **Copilot / platform guide** — "How do I publish a model to MAS in Viya?"
  → answer with citations from documentation.sas.com.
* **Investigation Assistant** — "What should I look at first today?" →
  prioritized alert triage; "Why did this alert fire, and is it a false
  positive?"
* **Procurement Integrity Analyst** — "Run the bid-rigging screen" (finds the
  planted Ministry of Education IT rotation ring), "Who are our riskiest
  suppliers?", "Estimate overpayment from price anomalies" — with charts.
* **Global Intelligence** — "What are other countries doing on AI-driven
  procurement oversight? Anything new this month?"

## Vendored code & licenses

`backend/sasviya/` and parts of `backend/saslogon.py` are adapted from
[sas-mcp-server](https://github.com/raedaldweik/sas-mcp-server) and its
use-case variant (© 2025 SAS Institute Inc., Apache-2.0 — headers retained).
`backend/websearch/` is adapted from the Web_Search news MCP server.
`backend/sasvi/` implements the scope planned in the SAS_VI_MCP roadmap.
