# SAS Viya connection settings shared by the MCP bridge (sasviya/tools.py)
# and the Visual Analytics toolset (sasva/tools.py). Reading the env is
# tolerant — the app boots without a Viya connection and the tools report a
# clear "not configured" error instead. The vendored official MCP server
# (backend/sas_mcp_server/) reads the same variables itself.

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sasviya")

SSL_VERIFY = os.getenv("SSL_VERIFY", "true").lower() not in ("false", "0", "no")

VIYA_ENDPOINT = os.getenv("VIYA_ENDPOINT", "").rstrip("/")
CLIENT_ID = os.getenv("CLIENT_ID", "sas-mcp")
# Optional OAuth client secret. Leave empty for a public client (PKCE /
# allowpublic); set it only when the client is registered as confidential.
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")

VIYA_USERNAME = os.getenv("VIYA_USERNAME", "")
VIYA_PASSWORD = os.getenv("VIYA_PASSWORD", "")
VIYA_REFRESH_TOKEN = os.getenv("VIYA_REFRESH_TOKEN", "")


def configured() -> bool:
    return bool(VIYA_ENDPOINT) and bool(
        VIYA_REFRESH_TOKEN or (VIYA_USERNAME and VIYA_PASSWORD))
