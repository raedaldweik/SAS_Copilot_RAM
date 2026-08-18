"""Configuration for the SAS Visual Investigator toolset.

The VI environment is configured independently of the Viya analytics
environment (they are different deployments), using VI_* variables with the
same conventions as the sas-vi-mcp server this toolset mirrors
(MCP_Servers -> "SAS VI MCP").
"""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sasvi")


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() not in ("false", "0", "no", "off")


VI_ENDPOINT = os.getenv("VI_ENDPOINT", "").rstrip("/")
# "sas.cli" ships on Viya, supports the password grant, and is the client
# used on the RACE demo environments (same default as sas-vi-mcp).
VI_CLIENT_ID = os.getenv("VI_CLIENT_ID", "sas.cli")
VI_CLIENT_SECRET = os.getenv("VI_CLIENT_SECRET", "")
VI_REFRESH_TOKEN = os.getenv("VI_REFRESH_TOKEN", "")
VI_USERNAME = os.getenv("VI_USERNAME", "")
VI_PASSWORD = os.getenv("VI_PASSWORD", "")
VI_SSL_VERIFY = _bool("VI_SSL_VERIFY", True)
VI_TIMEOUT = float(os.getenv("VI_TIMEOUT", "120"))

# Service base paths of a standard VI deployment (override only if an
# ingress rewrites paths). The workflow service mounts under svi-datahub.
VI_ALERT_BASE = os.getenv("VI_ALERT_BASE", "/svi-alert")
VI_DATAHUB_BASE = os.getenv("VI_DATAHUB_BASE", "/svi-datahub")
VI_SAND_BASE = os.getenv("VI_SAND_BASE", "/svi-sand")
VI_WORKFLOW_BASE = os.getenv("VI_WORKFLOW_BASE", "/svi-datahub/workflows")

SERVICE_BASES = {
    "alert": VI_ALERT_BASE,
    "datahub": VI_DATAHUB_BASE,
    "sand": VI_SAND_BASE,
    "workflows": VI_WORKFLOW_BASE,
}

# Write actions (dispositions, alert actions, workflow completion, generic
# POST/PUT) stay disabled unless explicitly enabled, so the triage copilot
# can never mutate the investigation environment by accident.
VI_ALLOW_ACTIONS = _bool("VI_ALLOW_ACTIONS", False)

# Cap on any single tool response so one verbose VI payload cannot blow up
# the agent's context window.
VI_MAX_CHARS = int(os.getenv("VI_MAX_CHARS", "16000"))

# Optional free-text description of what is deployed on this VI environment,
# surfaced to the agent via get_investigation_scope.
VI_USE_CASE = os.getenv(
    "VI_USE_CASE",
    "Procurement integrity monitoring: alerts on suppliers, tenders and "
    "payments flagged by detection scenarios, with entity networks and "
    "workflows for investigation.")


def configured() -> bool:
    return bool(VI_ENDPOINT) and bool(
        VI_REFRESH_TOKEN or (VI_USERNAME and VI_PASSWORD))
