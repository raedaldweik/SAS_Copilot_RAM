# SAS Agentic AI Copilot

A multi-agent AI assistant for the any organization — SAS-branded demo edition — demonstrating **SAS agentic AI with a
customer-owned LLM**. The same UI as the SAS RAM assistant, but with **no
SAS Retrieval Agent Manager dependency**: the agents run in this app against
Anthropic Claude and talk to SAS through the **official SAS Viya MCP
Server** (`sas-mcp-server` v1.7.0, vendored verbatim under
`backend/sas_mcp_server/` and bridged in-process over MCP).

> **The story for SAS:** SAS Copilot requires SAS-hosted LLMs. This app
> shows the alternative: RAM (or any agent host) + the SAS Viya MCP + the
> LLM of your choice — here Claude Sonnet 5, swappable for an on-prem model.
> The tool layer IS the official `sas-mcp-server` (the copilot talks to it
> through a real MCP client session), so everything demonstrated here
> transfers 1:1 to a RAM + MCP deployment.

## The four agents (dropdown in the UI)

| Agent | What it does | Backed by |
|---|---|---|
| **SAS Viya Copilot** | The complete platform: explore & profile data, run SAS code and batch jobs, build/edit VA reports, AutoML end to end, model ops & real-time scoring, and Intelligent Decisioning (rules → flows → publish → live decisions) — orchestrating seven tier-aligned specialists (SAS programmer, data explorer, data engineer, report designer, ML builder, model ops, decision architect) | The **official SAS Viya MCP Server**, all 74 tools / 9 tiers (`backend/sas_mcp_server/`, bridged by `backend/sasviya/`) |
| **Investigation Assistant** | Alert triage for SAS Visual Investigator: work the queue, explain why alerts fired, gather entity networks, flag false positives, recommend actions | VI environment via `backend/sasvi/` (svi-alert + svi-datahub REST) |
| **Procurement Integrity Analyst** | A per-use-case agent: tenders, bids, suppliers, invoices & red-flag alerts for government entities, with ready models (supplier risk, bid-rigging screen, price anomaly) | Bundled synthetic dataset + models (`backend/usecase/`) — runs with zero external dependencies |
| **Global Intelligence** | What other countries/agencies are doing, emerging tech, news monitoring with cited sources | Tavily web search (`backend/websearch/`, vendored from `Web_Search`) |

Everything an agent does is visible: live activity while it works, and a full
tool/LLM trace per answer (the grid icon under each response). Charts the
agents emit (`render_chart`) render as interactive SVG cards. Sub-agent steps
show up in the trace as `specialist › tool`.

**Arabic mode:** the عربي / English button in the header flips the whole UI
to Arabic (RTL layout, Arabic labels, Arabic voice input) and tells the
agents to answer in Modern Standard Arabic — and back again. The choice is
remembered per browser.

## Reports (SAS Visual Analytics)

The SAS Viya Copilot's `report_designer` specialist works VA reports
through the official MCP Server's Reports tier (Tier 3): find and read
reports (`list_reports`, `get_report_outline`, `describe_report_objects`),
create and edit them (`create_report`, `copy_report`,
`apply_report_operations`), and export shareable files (`export_report`).
It grounds every report in real CAS table columns before binding visuals,
and closes readouts with BI-consultant recommendations.

(The previous in-chat VA snapshot toolset still lives in `backend/sasva/`
but is not wired to any agent — the copilot uses only the official MCP
tools.)

## Architecture

```
frontend/  React + Vite + Tailwind (copied from Finance_RAM_UI, RAM plumbing removed)
backend/   FastAPI
  ├─ agents/      agent definitions + system prompts (registry.py, prompts.py)
  ├─ services/    the agentic loop (runner.py) + in-memory sessions (store.py)
  ├─ sas_mcp_server/  the official SAS Viya MCP Server, vendored verbatim (Apache-2.0)
  ├─ sasviya/     bridge: official MCP tools → agent runner (in-memory MCP client)
  ├─ sasva/       legacy VA snapshot toolset (kept in-tree, not wired to any agent)
  ├─ sasvi/       SAS Visual Investigator toolset (implements the SAS_VI_MCP roadmap)
  ├─ websearch/   Tavily tools      — vendored from Web_Search
  ├─ usecase/     bundled procurement-integrity data + models
  └─ toolset.py   shared tool registry + render_chart
```

* The LLM is **Claude Sonnet 5** (`MODEL` env var to change) driving a
  standard tool-use loop with streaming and prompt caching.
* The SAS Viya Copilot's tools come from the **official `sas-mcp-server`**,
  registered on an in-process FastMCP instance and called through a real
  in-memory MCP client session — actual MCP tools, schemas, and error
  semantics, with the whole app still shipping as **one container**.
  Default is the **complete surface: all 74 tools, tiers 0–7** (`MCP_TIERS`
  overrides; tier 8 is the Workbench-only variant of `execute_sas_code`).
  Because 74 tools is a lot for one context, the copilot is **multi-agent**:
  it keeps a compact core of cross-tier lookup tools for instant answers
  and delegates deep work to seven specialists, each owning one platform
  area (tiers 0+4 code & jobs, 1 discovery, 2 data ops, 3 reports,
  5 AutoML, 6 model ops, 7 decisioning). Pointing the bridge at an external
  MCP server (e.g. under RAM) is a wiring change, not a rewrite.
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

## Demo script ideas (SAS)

* **SAS Viya Copilot** — "Brainstorm a driver-risk dataset for a demo,
  generate 5,000 rows, profile it, then build a model with AutoML and score
  one record." Watch the copilot delegate to the data engineer → data
  explorer → ML builder → model ops in the trace.
* **Copilot / decisioning** — "Create a supplier-risk rule set and decision
  flow, publish it to MAS, and test a decision live" — the full Intelligent
  Decisioning lifecycle from chat.
* **Investigation Assistant** — "What should I look at first today?" →
  prioritized alert triage; "Why did this alert fire, and is it a false
  positive?"
* **Procurement Integrity Analyst** — "Run the bid-rigging screen" (finds the
  planted Ministry of Education IT rotation ring), "Who are our riskiest
  suppliers?", "Estimate overpayment from price anomalies" — with charts.
* **Global Intelligence** — "What are other countries doing on AI-driven
  procurement oversight? Anything new this month?"

## Vendored code & licenses

`backend/sas_mcp_server/` is the **official SAS Viya MCP Server** v1.7.0,
vendored verbatim from
[sas-mcp-server](https://github.com/raedaldweik/sas-mcp-server)
(© 2025–2026 SAS Institute Inc., Apache-2.0 — LICENSE and headers retained;
see `backend/sas_mcp_server/VENDORED.md` for the exact commit and update
instructions). Parts of `backend/saslogon.py` are adapted from the same
project's headless auth path. `backend/websearch/` is adapted from the
Web_Search news MCP server. `backend/sasvi/` implements the scope planned
in the SAS_VI_MCP roadmap.
