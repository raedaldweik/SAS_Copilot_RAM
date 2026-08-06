"""SAS Viya toolset — the official SAS Viya MCP Server, bridged in-process.

The official `sas-mcp-server` package (v1.7.0, Apache-2.0, SAS Institute
Inc.) is vendored verbatim under ``backend/sas_mcp_server/`` — see its
VENDORED.md. This module registers the official tool tiers on a FastMCP
instance and exposes them to the agent runner through an in-memory MCP
client session: the same tools, schemas, and behaviors an external MCP
client would see, shipped inside this one container.

Tier selection follows the official ``MCP_TIERS`` convention (spec strings
like ``"0-4"`` or ``"0,1,7"``). The default here skips Tier 3 (Reports) —
the chatbot's own `sasva` toolset owns the Visual Analytics experience,
with in-chat snapshot rendering the MCP tier doesn't do — Tier 7
(Decisioning authoring), and Tier 8 (Workbench, which re-registers
``execute_sas_code``).

Auth is the SASLogon refresh-token grant (`saslogon.SASLogonAuth`), handed
to the server through its ``get_token`` hook — no browser flow or
credential-cache file, so it works headless on Railway. Boot stays
tolerant: without a configured Viya connection the app still starts, the
tool specs are still published, and every call reports a clear "not
configured" error instead.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Optional

from saslogon import SASLogonAuth
from toolset import ToolError
from . import config
from .config import logger

auth = SASLogonAuth(
    endpoint=config.VIYA_ENDPOINT,
    client_id=config.CLIENT_ID,
    client_secret=config.CLIENT_SECRET,
    refresh_token=config.VIYA_REFRESH_TOKEN,
    username=config.VIYA_USERNAME,
    password=config.VIYA_PASSWORD,
    verify=config.SSL_VERIFY,
    label="SAS Viya",
)

MCP_TIERS = os.getenv("MCP_TIERS", "").strip() or "0-2,4-6"

# The official package validates VIYA_ENDPOINT at import. Give it a
# placeholder when none is set so the app can boot and publish tool specs;
# execute() gates every real call on config.configured() long before this
# placeholder could ever be dialed.
if not os.environ.get("VIYA_ENDPOINT"):
    os.environ["VIYA_ENDPOINT"] = "https://viya-not-configured.invalid"


class MCPToolSet:
    """A `toolset.ToolSet`-compatible view over an in-process MCP server.

    Same duck-typed surface the agent runner uses — ``specs()``,
    ``tool_names``, ``has()``, ``execute()`` — but the tools live on a
    FastMCP server and every call goes through a real MCP client session
    (in-memory transport), so schema validation and error semantics match
    an external MCP deployment exactly.
    """

    def __init__(self, name: str):
        self.name = name
        self._mcp = None                      # FastMCP server instance
        self._specs: dict[str, dict] = {}     # Anthropic tool specs by name
        self._client = None                   # persistent in-memory MCP client
        self._lock: Optional[asyncio.Lock] = None

    # ── registration (import time) ──────────────────────────────────
    def _build(self) -> None:
        from fastmcp import FastMCP
        from sas_mcp_server.tools import register_tools

        async def _get_token(ctx) -> str:
            try:
                return await auth.get_token()
            except Exception as e:
                # Surface auth problems as a clean message the agent can
                # explain, instead of a bare stack trace.
                raise ToolError(str(e)) from e

        self._mcp = FastMCP("SAS Viya MCP Server")
        register_tools(self._mcp, _get_token, tiers=MCP_TIERS)
        tools = asyncio.run(self._mcp.list_tools())
        for t in tools:
            mt = t.to_mcp_tool()
            self._specs[mt.name] = {
                "name": mt.name,
                "description": mt.description or "",
                "input_schema": mt.inputSchema,
            }
        logger.info("SAS Viya MCP bridge ready: %d tools (tiers %s)",
                    len(self._specs), MCP_TIERS)

    # ── ToolSet protocol ────────────────────────────────────────────
    @property
    def tool_names(self) -> list[str]:
        return list(self._specs.keys())

    def specs(self, only: Optional[list[str]] = None) -> list[dict]:
        names = only if only is not None else self.tool_names
        return [self._specs[n] for n in names if n in self._specs]

    def has(self, name: str) -> bool:
        return name in self._specs

    async def _session(self):
        """Open (once) and reuse one in-memory MCP client session."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._client is None:
                from fastmcp import Client
                client = Client(self._mcp)
                await client.__aenter__()
                self._client = client
        return self._client

    async def execute(self, name: str, args: dict) -> Any:
        if not config.configured():
            raise ToolError(
                "The SAS Viya environment is not configured. Tell the user "
                "to set VIYA_ENDPOINT plus credentials (VIYA_REFRESH_TOKEN, "
                "or VIYA_USERNAME and VIYA_PASSWORD) in the deployment "
                "environment variables and redeploy.")
        if self._mcp is None:
            raise ToolError(
                "The SAS Viya MCP bridge failed to initialize at startup — "
                "check the server logs for the import error.")
        from fastmcp.exceptions import ToolError as MCPToolError
        client = await self._session()
        try:
            result = await client.call_tool(name, args or {})
        except MCPToolError as e:
            raise ToolError(str(e)) from e
        return _unwrap(result)

    async def shutdown(self) -> None:
        """Close the MCP session and tear down warm compute sessions."""
        if self._client is not None:
            client, self._client = self._client, None
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                logger.exception("closing the MCP client session failed")
        try:
            from sas_mcp_server.viya_utils import shutdown_session_cache
            await shutdown_session_cache()
        except Exception:
            logger.exception("compute session cache shutdown failed")


def _unwrap(result: Any) -> Any:
    """Flatten a CallToolResult into plain JSON-able data for the runner."""
    data = getattr(result, "data", None)
    if data is not None:
        return _jsonable(data)
    structured = getattr(result, "structured_content", None)
    if structured:
        return structured
    parts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    text = "\n".join(parts)
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def _jsonable(value: Any) -> Any:
    """Recursively convert pydantic models / rich types to JSON-able data."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:
            return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


viya = MCPToolSet("sas_viya")
try:
    viya._build()
except Exception:
    # Tolerant boot: the app (and the other agents) must come up even if the
    # bridge cannot — execute() then reports the failure per call.
    logger.exception("SAS Viya MCP bridge failed to initialize")
