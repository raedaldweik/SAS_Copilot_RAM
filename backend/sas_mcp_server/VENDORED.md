# Vendored: the official SAS Viya MCP Server

This directory is a **verbatim copy** of the official SAS Viya MCP Server
Python package (`src/sas_mcp_server/`):

- Source repository: https://github.com/raedaldweik/sas-mcp-server
  (mirror of the official SAS `sas-mcp-server`)
- Version: **1.7.0**
- Commit: `9d32c872e1d755d82a48ae886f223575811a0d5f`
- License: Apache-2.0 (see `LICENSE` in this directory)
- Copyright © 2025–2026, SAS Institute Inc., Cary, NC, USA

## How it is used here

The SAS Viya Copilot agent connects to this server in-process:
`backend/sasviya/tools.py` registers the official tool tiers on a FastMCP
instance and talks to it through an in-memory MCP client session — the same
tools, schemas, and behaviors an external MCP client would see, shipped
inside the one app container. Authentication is a SASLogon refresh-token
grant supplied per call through the server's `get_token` hook (see
`backend/saslogon.py`), so no browser flow or credential cache is needed at
runtime.

## Updating

Do **not** edit files in this directory. To upgrade, re-copy
`src/sas_mcp_server/` from the source repository at the desired tag and
update the version/commit above.
