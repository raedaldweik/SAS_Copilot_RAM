"""SAS Visual Investigator toolset — alert triage and entity investigation.

In-process port of the sas-vi-mcp server (MCP_Servers -> "SAS VI MCP"): the
same tool surface, grounded in the official VI 2026.04 OpenAPI specs
(svi-alert v6, svi-datahub v11, svi-sand v10, workflows v4) instead of the
old candidate-endpoint guessing. Read tools cover triage, entities, search,
network and workflow; write tools are gated behind VI_ALLOW_ACTIONS.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from saslogon import SASLogonAuth
from toolset import ToolSet, ToolError
from . import config
from .config import logger

auth = SASLogonAuth(
    endpoint=config.VI_ENDPOINT,
    client_id=config.VI_CLIENT_ID,
    client_secret=config.VI_CLIENT_SECRET,
    refresh_token=config.VI_REFRESH_TOKEN,
    username=config.VI_USERNAME,
    password=config.VI_PASSWORD,
    verify=config.VI_SSL_VERIFY,
    label="SAS Visual Investigator",
)

vi = ToolSet("sas_vi")

_TRIAGE_ACTION_CT = "application/vnd.sas.investigation.triage.action.request+json"
_SEARCH_CT = "application/vnd.sas.sand.search.request+json"
_GRAPH_CT = "application/vnd.sas.sand.graph.request+json"
_RELATED_CT = "application/vnd.sas.sand.related.objects.request+json"
_WF_ACTION_CT = "application/vnd.sas.investigation.workflow.action+json"
# The workflow service varies responses by client; desktop matches the VI UI.
_WF_HEADERS = {"VI-Client-Application": "desktop"}


# ── request plumbing ────────────────────────────────────────────────


def _service_url(service: str, path: str) -> str:
    try:
        base = config.SERVICE_BASES[service]
    except KeyError:
        raise ToolError(
            f"Unknown VI service '{service}'. Valid services: "
            f"{', '.join(sorted(config.SERVICE_BASES))}.") from None
    if not path.startswith("/"):
        path = "/" + path
    return f"{config.VI_ENDPOINT}{base}{path}"


def _error_detail(resp: httpx.Response) -> str:
    """Pull the human-readable message out of a SAS error payload."""
    try:
        body = resp.json()
        if isinstance(body, dict):
            parts = [str(body[k]) for k in ("message", "details",
                                            "error_description")
                     if body.get(k)]
            if parts:
                return "; ".join(parts)[:400]
    except Exception:
        pass
    return resp.text[:400]


def _hint_for_status(status: int, service: str, path: str) -> str:
    if status == 401:
        return ("Authentication was rejected even after refreshing the "
                "token. Verify the credentials and that the account is a "
                "VI user.")
    if status == 403:
        return ("The signed-in account lacks permission for this resource. "
                "Check its VI group/capability assignments.")
    if status == 404:
        return (f"'{path}' was not found on the {service} service. The "
                "record ID or type name may be wrong — list the available "
                "items first (e.g. list_entity_types, list_alerts).")
    if status == 400:
        return ("The request was malformed for this deployment — check "
                "filter/sortBy syntax and field names before retrying.")
    if status >= 500:
        return ("The VI service errored internally. Retry once; if it "
                "persists, check the service's health in the environment.")
    return ""


def compact(value: Any, limit: Optional[int] = None) -> Any:
    """Cap a JSON payload's serialized size so one verbose VI response can't
    blow up the agent's context. Returns the value unchanged when it fits."""
    limit = limit or config.VI_MAX_CHARS
    try:
        text = json.dumps(value, default=str)
    except Exception:
        return str(value)[:limit]
    if len(text) <= limit:
        return value
    return {
        "truncated": True,
        "note": (f"Response was {len(text)} characters; showing the first "
                 f"{limit}. Request fewer items (lower limit), a narrower "
                 "filter, or a specific record instead."),
        "preview": text[:limit],
    }


async def vi_request(
    method: str,
    service: str,
    path: str,
    *,
    params: Optional[dict] = None,
    body: Any = None,
    content_type: Optional[str] = None,
    headers: Optional[dict] = None,
) -> Any:
    """One authenticated request against a VI service (alert | datahub |
    sand | workflows), with a single re-auth retry on 401 and shaped,
    actionable errors."""
    url = _service_url(service, path)
    token = await auth.get_token()

    req_headers = {"Authorization": f"Bearer {token}",
                   "Accept": "application/json"}
    if content_type:
        req_headers["Content-Type"] = content_type
    if headers:
        req_headers.update(headers)

    async with httpx.AsyncClient(verify=config.VI_SSL_VERIFY,
                                 timeout=config.VI_TIMEOUT,
                                 follow_redirects=True) as client:
        try:
            resp = await client.request(
                method, url, params=params or None,
                json=body if body is not None else None,
                headers=req_headers)
            if resp.status_code == 401:
                # Token may have been revoked server-side — refresh once.
                auth.invalidate()
                token = await auth.get_token()
                req_headers["Authorization"] = f"Bearer {token}"
                resp = await client.request(
                    method, url, params=params or None,
                    json=body if body is not None else None,
                    headers=req_headers)
        except httpx.HTTPError as e:
            raise ToolError(
                f"Could not reach {url}: {e}. If VI is behind a cloudflared "
                "quick tunnel, the tunnel may have restarted with a new "
                "URL — update VI_ENDPOINT to the current tunnel address.") from e

    if resp.status_code >= 400:
        detail = _error_detail(resp)
        hint = _hint_for_status(resp.status_code, service, path)
        logger.warning("VI %s %s -> %s: %s", method, url, resp.status_code,
                       detail)
        raise ToolError(
            f"{method} {config.SERVICE_BASES[service]}{path} failed with "
            f"HTTP {resp.status_code}: {detail}"
            + (f" — {hint}" if hint else ""))

    if resp.status_code == 204 or not resp.content:
        return {"status": resp.status_code, "ok": True}
    try:
        return resp.json()
    except json.JSONDecodeError:
        return resp.text[: config.VI_MAX_CHARS]


def _require_actions_enabled(action: str) -> None:
    if not config.VI_ALLOW_ACTIONS:
        raise ToolError(
            f"'{action}' modifies the investigation environment, and write "
            "actions are disabled (VI_ALLOW_ACTIONS=false). Set "
            "VI_ALLOW_ACTIONS=true in the deployment's environment "
            "variables to enable dispositions and workflow actions.")


# ── response shaping ────────────────────────────────────────────────


def _pick(record: dict, *names: str) -> Any:
    for name in names:
        value = record.get(name)
        if value is not None:
            return value
    return None


def _collection_items(data: Any) -> tuple[list, Optional[int]]:
    """(items, count) from a SAS collection, tolerating {items,count}
    envelopes and bare lists."""
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            count = data.get("count")
            return items, count if isinstance(count, int) else None
        return [data], None
    if isinstance(data, list):
        return data, len(data)
    return [], None


def _shape_alert(a: dict) -> dict:
    shaped = {
        "id": _pick(a, "id", "alertId"),
        "label": _pick(a, "label", "name", "displayName", "title"),
        "score": _pick(a, "score", "totalScore", "alertScore"),
        "status": _pick(a, "status", "state", "dispositionStatus"),
        "queue": _pick(a, "queueName", "queue", "queueId"),
        "strategy": _pick(a, "strategyName", "strategyId"),
        "domain": _pick(a, "domainName", "domainId"),
        "entityType": _pick(a, "entityType", "objectTypeName", "documentType"),
        "entityId": _pick(a, "entityId", "objectId", "documentId"),
        "entityLabel": _pick(a, "entityLabel", "objectLabel"),
        "assignedTo": _pick(a, "assignedTo", "owner", "assignee",
                            "checkedOutBy"),
        "createdAt": _pick(a, "createdTimeStamp", "createdTimestamp",
                           "creationTimeStamp"),
        "modifiedAt": _pick(a, "modifiedTimeStamp", "modifiedTimestamp"),
    }
    shaped = {k: v for k, v in shaped.items() if v is not None}
    # Scenario/reason info is the heart of triage.
    for key in ("scenarios", "scenarioNames", "reasons",
                "contributingScenarios"):
        if a.get(key) is not None:
            shaped[key] = a[key]
            break
    return shaped or a


def _shape_fired_event(e: dict) -> dict:
    shaped = {
        "id": _pick(e, "id", "sfeId", "scenarioFiredEventId"),
        "scenario": _pick(e, "scenarioName", "scenarioLabel", "scenarioId"),
        "score": _pick(e, "score", "eventScore", "contribution"),
        "message": _pick(e, "message", "description", "label"),
        "disposition": _pick(e, "disposition", "dispositionName",
                             "dispositionId"),
        "firedAt": _pick(e, "createdTimeStamp", "creationTimeStamp",
                         "firedTimestamp"),
        "entityType": _pick(e, "entityType", "objectTypeName"),
        "entityId": _pick(e, "entityId", "objectId"),
    }
    for key in ("outputValues", "values", "eventValues", "attributes"):
        if e.get(key) is not None:
            shaped[key] = e[key]
            break
    shaped = {k: v for k, v in shaped.items() if v is not None}
    return shaped or e


def _shape_entity_type(t: dict) -> dict:
    shaped = {
        "name": _pick(t, "name", "typeName"),
        "label": _pick(t, "label", "displayName"),
        "description": _pick(t, "description"),
        "kind": _pick(t, "storedObjectType", "type", "kind"),
    }
    shaped = {k: v for k, v in shaped.items() if v is not None}
    return shaped or t


def _shape_relationship_type(r: dict) -> dict:
    shaped = {
        "name": _pick(r, "name", "relationshipTypeName"),
        "label": _pick(r, "label", "displayName"),
        "from": _pick(r, "fromEntityTypeName", "sourceTypeName",
                      "fromObjectTypeName"),
        "to": _pick(r, "toEntityTypeName", "targetTypeName",
                    "toObjectTypeName"),
        "description": _pick(r, "description"),
    }
    shaped = {k: v for k, v in shaped.items() if v is not None}
    return shaped or r


def _shape_search_hit(hit: dict) -> dict:
    shaped = {
        "type": _pick(hit, "type", "objectTypeName"),
        "id": _pick(hit, "id", "objectId"),
        "label": _pick(hit, "label", "displayLabel", "title"),
        "score": _pick(hit, "score", "relevance"),
    }
    for key in ("fields", "summary", "highlights", "values"):
        if hit.get(key) is not None:
            shaped[key] = hit[key]
            break
    shaped = {k: v for k, v in shaped.items() if v is not None}
    return shaped or hit


def _shape_graph(data: dict) -> dict:
    if not isinstance(data, dict):
        return {"raw": data}
    vertices = data.get("vertices") or data.get("nodes") or []
    edges = data.get("edges") or data.get("links") or []
    shaped_vertices = []
    for v in vertices if isinstance(vertices, list) else []:
        shaped_vertices.append({k: v.get(src) for k, src in (
            ("type", "type"), ("id", "id"), ("label", "label"),
            ("degree", "degree")) if v.get(src) is not None} or v)
    shaped_edges = []
    for e in edges if isinstance(edges, list) else []:
        shaped_edges.append({k: e.get(src) for k, src in (
            ("type", "type"), ("id", "id"), ("label", "label"),
            ("from", "from"), ("to", "to"),
            ("source", "source"), ("target", "target"))
            if e.get(src) is not None} or e)
    return {"vertexCount": len(shaped_vertices),
            "edgeCount": len(shaped_edges),
            "vertices": shaped_vertices,
            "edges": shaped_edges}


def _shape_task(t: dict) -> dict:
    shaped = {
        "id": _pick(t, "id", "taskId"),
        "name": _pick(t, "name", "label", "taskName"),
        "state": _pick(t, "state", "status"),
        "assignee": _pick(t, "assignee", "claimedBy", "owner"),
        "processId": _pick(t, "processId", "workflowProcessId"),
        "workflow": _pick(t, "workflowName", "processDefinitionName"),
        "entityType": _pick(t, "entityName", "entityTypeName"),
        "entityInstanceId": _pick(t, "entityInstanceId"),
        "createdAt": _pick(t, "createdTimeStamp", "creationTimeStamp",
                           "startTime"),
        "dueAt": _pick(t, "dueDate", "dueTimeStamp"),
    }
    if t.get("actions") is not None:
        shaped["actions"] = [
            {"id": a.get("id"), "name": a.get("name")}
            if isinstance(a, dict) else a
            for a in (t["actions"] if isinstance(t["actions"], list) else [])
        ]
    shaped = {k: v for k, v in shaped.items() if v is not None}
    return shaped or t


def _shape_process(p: dict) -> dict:
    shaped = {
        "id": _pick(p, "id", "processId"),
        "workflow": _pick(p, "workflowName", "processDefinitionName", "name"),
        "state": _pick(p, "state", "status"),
        "suspended": _pick(p, "suspended"),
        "entityType": _pick(p, "entityName", "entityTypeName"),
        "entityInstanceId": _pick(p, "entityInstanceId"),
        "startedAt": _pick(p, "startTime", "createdTimeStamp",
                           "creationTimeStamp"),
        "endedAt": _pick(p, "endTime"),
    }
    shaped = {k: v for k, v in shaped.items() if v is not None}
    return shaped or p


# ── scope & diagnostics ─────────────────────────────────────────────


@vi.add(
    "get_investigation_scope",
    "Describe this assistant's investigation scope: what the connected SAS "
    "Visual Investigator environment contains, which capabilities are "
    "available, and whether write actions are enabled. Call this first in a "
    "new conversation.",
    {"type": "object", "properties": {}},
)
async def get_investigation_scope():
    logger.info("--- TOOL USED: get_investigation_scope ---")
    return {
        "environment": config.VI_ENDPOINT or "(not configured)",
        "configured": config.configured(),
        "useCase": config.VI_USE_CASE,
        "writeActionsEnabled": config.VI_ALLOW_ACTIONS,
        "capabilities": {
            "alerts": "triage queue: list_alerts, get_alert, "
                      "get_alert_scorecard, get_alert_fired_events, "
                      "dispositions and alert actions",
            "entities": "data hub: list_entity_types, list_entities, "
                        "get_entity, get_related_entities, comments",
            "search": "free-text search across all indexed data: "
                      "search_investigator",
            "network": "link analysis: get_entity_network, "
                       "find_related_entities",
            "workflow": "investigation workflows: list_workflow_tasks, "
                        "get_workflow_task, processes",
        },
        "guidance": (
            "Typical triage flow: list_alerts (sorted by score) -> "
            "get_alert + get_alert_fired_events to see WHY it fired -> "
            "get_entity + get_entity_network on the flagged entity -> "
            "recommend a disposition."),
    }


@vi.add(
    "check_vi_connection",
    "Verify connectivity and authentication against the Visual Investigator "
    "environment. Use when another tool reports connection or sign-in "
    "problems, to tell configuration errors apart from data questions.",
    {"type": "object", "properties": {}},
)
async def check_vi_connection():
    logger.info("--- TOOL USED: check_vi_connection ---")
    if not config.VI_ENDPOINT:
        return {"ok": False,
                "problem": "VI_ENDPOINT is not set",
                "fix": "Set VI_ENDPOINT in the deployment's environment "
                       "variables (the VI base URL or the current "
                       "cloudflared tunnel URL)."}
    checks = {}
    overall = True
    for service, path in (("alert", "/"), ("sand", "/")):
        try:
            await vi_request("GET", service, path)
            checks[service] = "ok"
        except Exception as e:
            checks[service] = str(e)[:200]
            overall = False
    return {"ok": overall, "endpoint": config.VI_ENDPOINT,
            "services": checks,
            "writeActionsEnabled": config.VI_ALLOW_ACTIONS}


# ── alerts (svi-alert v6) ───────────────────────────────────────────


@vi.add(
    "list_alerts",
    "List alerts in the Visual Investigator triage queue, highest score "
    "first by default. Returns compact records (id, label, score, status, "
    "queue, flagged entity). Use `filter` with SAS REST filter syntax to "
    "narrow, e.g. contains(label,'ACME') or eq(status,'OPEN'); use "
    "sort_by='' if the deployment rejects the score sort.",
    {"type": "object",
     "properties": {
         "start": {"type": "integer", "description": "Offset for paging (default 0)."},
         "limit": {"type": "integer", "description": "Maximum alerts (default 25)."},
         "sort_by": {"type": "string", "description": "sortBy criteria (default 'score:descending'; '' to disable)."},
         "filter": {"type": "string", "description": "SAS REST filter expression."}},
     },
)
async def list_alerts(start: int = 0, limit: int = 25,
                      sort_by: str = "score:descending",
                      filter: Optional[str] = None):
    logger.info("--- TOOL USED: list_alerts ---")
    params: dict = {"start": start, "limit": limit}
    if sort_by:
        params["sortBy"] = sort_by
    if filter:
        params["filter"] = filter
    data = await vi_request("GET", "alert", "/alerts", params=params)
    items, count = _collection_items(data)
    return compact({
        "count": count if count is not None else len(items),
        "returned": len(items),
        "alerts": [_shape_alert(a) for a in items],
    })


@vi.add(
    "get_alert",
    "Get the full record of one alert by ID: scores, status, queue and "
    "routing, the flagged entity, and disposition/workflow state.",
    {"type": "object", "properties": {"alert_id": {"type": "string"}},
     "required": ["alert_id"]},
)
async def get_alert(alert_id: str):
    logger.info("--- TOOL USED: get_alert ---")
    return compact(await vi_request("GET", "alert", f"/alerts/{alert_id}"))


@vi.add(
    "get_alert_fired_events",
    "Get the scenario-fired events behind one alert — the specific "
    "detections that raised it and their evidence values. Essential for "
    "explaining WHY an alert fired and judging false positives.",
    {"type": "object",
     "properties": {
         "alert_id": {"type": "string"},
         "start": {"type": "integer", "description": "Offset (default 0)."},
         "limit": {"type": "integer", "description": "Maximum events (default 25)."}},
     "required": ["alert_id"]},
)
async def get_alert_fired_events(alert_id: str, start: int = 0,
                                 limit: int = 25):
    logger.info("--- TOOL USED: get_alert_fired_events ---")
    data = await vi_request(
        "GET", "alert", f"/alerts/{alert_id}/scenarioFiredEvents",
        params={"start": start, "limit": limit})
    items, count = _collection_items(data)
    return compact({
        "alertId": alert_id,
        "count": count if count is not None else len(items),
        "firedEvents": [_shape_fired_event(e) for e in items],
    })


@vi.add(
    "get_alert_scorecard",
    "Get the scorecard for one alert: how each contributing scenario's "
    "score rolls up into the alert's total. Use to explain the score "
    "composition to an investigator.",
    {"type": "object", "properties": {"alert_id": {"type": "string"}},
     "required": ["alert_id"]},
)
async def get_alert_scorecard(alert_id: str):
    logger.info("--- TOOL USED: get_alert_scorecard ---")
    return compact(await vi_request(
        "GET", "alert", f"/alerts/{alert_id}/scorecard",
        params={"includeScenarioFiredEventLabels": "true"}))


@vi.add(
    "list_alert_queues",
    "List the alert queues (work baskets) configured in Visual "
    "Investigator, e.g. to say where an alert can be routed.",
    {"type": "object",
     "properties": {"start": {"type": "integer"},
                    "limit": {"type": "integer"}}},
)
async def list_alert_queues(start: int = 0, limit: int = 50):
    logger.info("--- TOOL USED: list_alert_queues ---")
    return compact(await vi_request(
        "GET", "alert", "/queues", params={"start": start, "limit": limit}))


@vi.add(
    "list_alert_strategies",
    "List the alerting strategies (how scenario events are grouped into "
    "alerts per entity type). Useful for understanding the detection setup "
    "behind the triage queue.",
    {"type": "object",
     "properties": {"start": {"type": "integer"},
                    "limit": {"type": "integer"}}},
)
async def list_alert_strategies(start: int = 0, limit: int = 50):
    logger.info("--- TOOL USED: list_alert_strategies ---")
    return compact(await vi_request(
        "GET", "alert", "/strategies",
        params={"start": start, "limit": limit}))


@vi.add(
    "list_alert_dispositions",
    "List the dispositions (close/suppress/escalate decisions) that are "
    "configured. Pass alert_id to see only the dispositions valid for that "
    "alert — do this before disposition_alert.",
    {"type": "object", "properties": {"alert_id": {"type": "string"}}},
)
async def list_alert_dispositions(alert_id: Optional[str] = None):
    logger.info("--- TOOL USED: list_alert_dispositions ---")
    path = (f"/alerts/{alert_id}/alertDispositions"
            if alert_id else "/alertDispositions")
    return compact(await vi_request("GET", "alert", path))


@vi.add(
    "disposition_alert",
    "Apply a disposition to one alert (e.g. close as false positive, "
    "escalate to a case). Requires VI_ALLOW_ACTIONS=true. Get valid "
    "disposition IDs from list_alert_dispositions(alert_id) first, and only "
    "act after the user has explicitly confirmed.",
    {"type": "object",
     "properties": {
         "alert_id": {"type": "string"},
         "disposition_id": {"type": "string"},
         "queue_id": {"type": "string", "description": "Optional queue to route to."}},
     "required": ["alert_id", "disposition_id"]},
)
async def disposition_alert(alert_id: str, disposition_id: str,
                            queue_id: Optional[str] = None):
    logger.info("--- TOOL USED: disposition_alert ---")
    _require_actions_enabled("disposition_alert")
    body: dict = {"dispositionId": disposition_id}
    if queue_id:
        body["queueId"] = queue_id
    data = await vi_request(
        "POST", "alert",
        f"/alerts/{alert_id}/alertDecisions/{disposition_id}",
        body=body, content_type=_TRIAGE_ACTION_CT)
    return compact({"alertId": alert_id, "dispositionId": disposition_id,
                    "result": data})


@vi.add(
    "perform_alert_action",
    "Perform a triage action on one alert. action_type is one of CHECKOUT "
    "(claim it), CHECKIN (release it), ASSIGNMENT (assign to `user`), "
    "REACTIVATE. Requires VI_ALLOW_ACTIONS=true and explicit user "
    "confirmation.",
    {"type": "object",
     "properties": {
         "alert_id": {"type": "string"},
         "action_type": {"type": "string",
                         "enum": ["CHECKOUT", "CHECKIN", "ASSIGNMENT",
                                  "REACTIVATE"]},
         "user": {"type": "string", "description": "Target user for ASSIGNMENT."}},
     "required": ["alert_id", "action_type"]},
)
async def perform_alert_action(alert_id: str, action_type: str,
                               user: Optional[str] = None):
    logger.info("--- TOOL USED: perform_alert_action ---")
    _require_actions_enabled("perform_alert_action")
    action_type = (action_type or "").upper()
    valid = ("CHECKOUT", "CHECKIN", "ASSIGNMENT", "REACTIVATE")
    if action_type not in valid:
        raise ToolError(f"action_type must be one of {', '.join(valid)}")
    body: dict = {"alertId": alert_id, "actionType": action_type}
    if user:
        body["user"] = user
    data = await vi_request(
        "POST", "alert", f"/alerts/{alert_id}/alertActions/{action_type}",
        body=body, content_type=_TRIAGE_ACTION_CT)
    return compact({"alertId": alert_id, "action": action_type,
                    "result": data})


# ── entities (svi-datahub v11) ──────────────────────────────────────


@vi.add(
    "list_entity_types",
    "List the entity types defined in the Visual Investigator data hub "
    "(e.g. supplier, tender, payment, person). Call this before listing or "
    "reading entities so you use exact type names.",
    {"type": "object", "properties": {}},
)
async def list_entity_types():
    logger.info("--- TOOL USED: list_entity_types ---")
    data = await vi_request(
        "GET", "datahub", "/admin/storedObjects/listAll",
        params={"excludeUnauthorized": "true"})
    items, _ = _collection_items(data)
    return compact({
        "count": len(items),
        "entityTypes": [_shape_entity_type(t) for t in items],
    })


@vi.add(
    "list_relationship_types",
    "List the relationship types defined between entity types (e.g. "
    "supplier -[has_director]-> person). Use the returned names with "
    "get_related_entities.",
    {"type": "object", "properties": {}},
)
async def list_relationship_types():
    logger.info("--- TOOL USED: list_relationship_types ---")
    data = await vi_request("GET", "datahub", "/admin/relationships")
    items, _ = _collection_items(data)
    return compact({
        "count": len(items),
        "relationshipTypes": [_shape_relationship_type(r) for r in items],
    })


@vi.add(
    "list_entities",
    "List records of one entity type from the data hub, with display "
    "labels. Use exact type names from list_entity_types.",
    {"type": "object",
     "properties": {
         "entity_type": {"type": "string"},
         "start": {"type": "integer"},
         "limit": {"type": "integer"}},
     "required": ["entity_type"]},
)
async def list_entities(entity_type: str, start: int = 0, limit: int = 25):
    logger.info("--- TOOL USED: list_entities (%s) ---", entity_type)
    return compact(await vi_request(
        "GET", "datahub", f"/documents/{entity_type}",
        params={"start": start, "limit": limit,
                "includeDisplayLabel": "true"}))


@vi.add(
    "get_entity",
    "Read one entity record in full (e.g. a supplier's complete profile). "
    "include_children also returns nested child documents.",
    {"type": "object",
     "properties": {
         "entity_type": {"type": "string"},
         "entity_id": {"type": "string"},
         "include_children": {"type": "boolean", "description": "Default true."}},
     "required": ["entity_type", "entity_id"]},
)
async def get_entity(entity_type: str, entity_id: str,
                     include_children: bool = True):
    logger.info("--- TOOL USED: get_entity ---")
    return compact(await vi_request(
        "GET", "datahub", f"/documents/{entity_type}/{entity_id}",
        params={"depth": "max" if include_children else "0",
                "includeDisplayLabel": "true"}))


@vi.add(
    "get_related_entities",
    "Follow one relationship type from an entity to its related records "
    "(e.g. supplier -> its payments). Get valid relationship names from "
    "list_relationship_types. For the whole neighbourhood at once use "
    "get_entity_network instead.",
    {"type": "object",
     "properties": {
         "entity_type": {"type": "string"},
         "entity_id": {"type": "string"},
         "relationship_type": {"type": "string"},
         "start": {"type": "integer"},
         "limit": {"type": "integer"}},
     "required": ["entity_type", "entity_id", "relationship_type"]},
)
async def get_related_entities(entity_type: str, entity_id: str,
                               relationship_type: str, start: int = 0,
                               limit: int = 25):
    logger.info("--- TOOL USED: get_related_entities ---")
    return compact(await vi_request(
        "GET", "datahub",
        f"/documents/{entity_type}/{entity_id}/{relationship_type}",
        params={"start": start, "limit": limit}))


@vi.add(
    "get_entity_comments",
    "Read the investigator comments recorded on an entity — prior analyst "
    "findings and context that should inform any recommendation.",
    {"type": "object",
     "properties": {
         "entity_type": {"type": "string"},
         "entity_id": {"type": "string"},
         "start": {"type": "integer"},
         "limit": {"type": "integer"}},
     "required": ["entity_type", "entity_id"]},
)
async def get_entity_comments(entity_type: str, entity_id: str,
                              start: int = 0, limit: int = 25):
    logger.info("--- TOOL USED: get_entity_comments ---")
    return compact(await vi_request(
        "GET", "datahub",
        f"/documents/{entity_type}/{entity_id}/comments",
        params={"start": start, "limit": limit}))


@vi.add(
    "get_entity_attachments",
    "List the file attachments on an entity (names and metadata only, not "
    "the file contents).",
    {"type": "object",
     "properties": {
         "entity_type": {"type": "string"},
         "entity_id": {"type": "string"}},
     "required": ["entity_type", "entity_id"]},
)
async def get_entity_attachments(entity_type: str, entity_id: str):
    logger.info("--- TOOL USED: get_entity_attachments ---")
    return compact(await vi_request(
        "GET", "datahub",
        f"/documents/{entity_type}/{entity_id}/attachments"))


# ── search & network (svi-sand v10) ─────────────────────────────────


@vi.add(
    "search_investigator",
    "Free-text search across everything indexed in Visual Investigator "
    "(suppliers, tenders, payments, persons, ...). Supports lucene syntax "
    "(e.g. 'ACME', 'name:acme~ AND country:AE'). Use this to find an entity "
    "before pulling its details. Restrict with entity_types (exact names "
    "from list_entity_types) when you know what you're looking for.",
    {"type": "object",
     "properties": {
         "query": {"type": "string", "description": "Free-text / lucene query."},
         "entity_types": {"type": "array", "items": {"type": "string"},
                          "description": "Optional list of type names to restrict to."},
         "limit": {"type": "integer", "description": "Maximum hits (default 25)."}},
     "required": ["query"]},
)
async def search_investigator(query: str,
                              entity_types: Optional[list] = None,
                              limit: int = 25):
    logger.info("--- TOOL USED: search_investigator (%s) ---", query)
    body: dict = {
        "query": {"type": "text", "language": "lucene", "text": query},
        "visualizations": {
            "hits": {"type": "hits"},
            "results": {
                "type": "summary",
                "start": 1,
                "limit": max(1, min(limit, 200)),
                "order": {"type": "score", "direction": "descending"},
            },
        },
    }
    if entity_types:
        body["types"] = entity_types

    data = await vi_request("POST", "sand", "/searches", body=body,
                            content_type=_SEARCH_CT)

    viz = data.get("visualizations", data) if isinstance(data, dict) else {}
    hits = viz.get("hits", {}) if isinstance(viz, dict) else {}
    results = viz.get("results", {}) if isinstance(viz, dict) else {}
    raw_items = []
    if isinstance(results, dict):
        for key in ("objects", "summaries", "items", "results", "hits"):
            if isinstance(results.get(key), list):
                raw_items = results[key]
                break
    if not raw_items and isinstance(data, dict) \
            and isinstance(data.get("items"), list):
        raw_items = data["items"]

    shaped = [_shape_search_hit(h) for h in raw_items if isinstance(h, dict)]
    out: dict = {"query": query, "returned": len(shaped), "results": shaped}
    if isinstance(hits, dict):
        for key in ("count", "total", "value"):
            if hits.get(key) is not None:
                out["totalHits"] = hits[key]
                break
    if not shaped:
        out["raw"] = data   # don't hide an unexpected response shape
    return compact(out)


@vi.add(
    "get_entity_network",
    "Get the relationship network around one entity — who/what it is "
    "directly linked to (the VI link-analysis canvas as data). Returns "
    "vertices and edges you can narrate or chart. expansion_limit caps "
    "neighbours per vertex to keep output focused.",
    {"type": "object",
     "properties": {
         "entity_type": {"type": "string"},
         "entity_id": {"type": "string"},
         "expansion_limit": {"type": "integer", "description": "Max neighbours per vertex (default 25)."}},
     "required": ["entity_type", "entity_id"]},
)
async def get_entity_network(entity_type: str, entity_id: str,
                             expansion_limit: int = 25):
    logger.info("--- TOOL USED: get_entity_network ---")
    body = {
        "query": {
            "type": "object",
            "objectIds": [{"type": entity_type, "id": entity_id}],
        },
    }
    data = await vi_request(
        "POST", "sand", "/graphs", body=body, content_type=_GRAPH_CT,
        params={"expansionLimit": max(1, min(expansion_limit, 100)),
                "calculateMetrics": "false"})
    shaped = _shape_graph(data if isinstance(data, dict) else {})
    shaped["seed"] = {"type": entity_type, "id": entity_id}
    if not shaped.get("vertexCount") and isinstance(data, dict):
        shaped["raw"] = data
    return compact(shaped)


@vi.add(
    "find_related_entities",
    "Find entities connected to a start entity within N relationship hops, "
    "optionally restricted to target types — e.g. from a flagged supplier, "
    "find other suppliers reachable via shared directors or addresses "
    "within 2 hops. The go-to tool for 'who else is connected?' questions.",
    {"type": "object",
     "properties": {
         "start_type": {"type": "string"},
         "start_id": {"type": "string"},
         "end_types": {"type": "array", "items": {"type": "string"},
                       "description": "Optional target type names."},
         "hops": {"type": "integer", "description": "Max hops 1-4 (default 2)."},
         "limit": {"type": "integer", "description": "Max paths (default 20)."}},
     "required": ["start_type", "start_id"]},
)
async def find_related_entities(start_type: str, start_id: str,
                                end_types: Optional[list] = None,
                                hops: int = 2, limit: int = 20):
    logger.info("--- TOOL USED: find_related_entities ---")
    body: dict = {
        "startQuery": {
            "type": "object",
            "objectIds": [{"type": start_type, "id": start_id}],
        },
        "hops": max(1, min(hops, 4)),
    }
    if end_types:
        body["endTypes"] = end_types
    data = await vi_request(
        "POST", "sand", "/relatedObjects", body=body,
        content_type=_RELATED_CT,
        params={"start": 0, "limit": max(1, min(limit, 100))})
    return compact({
        "start": {"type": start_type, "id": start_id},
        "hops": body["hops"],
        "related": data,
    })


# ── workflow (workflows v4, mounted under svi-datahub) ──────────────


@vi.add(
    "list_workflow_tasks",
    "List investigation workflow tasks. only_workable=true returns just the "
    "tasks the signed-in account is allowed to work — set false to see "
    "every open task (e.g. for a workload overview).",
    {"type": "object",
     "properties": {
         "only_workable": {"type": "boolean", "description": "Default true."},
         "start": {"type": "integer"},
         "limit": {"type": "integer"},
         "filter": {"type": "string", "description": "Optional filter expression."}},
     },
)
async def list_workflow_tasks(only_workable: bool = True, start: int = 0,
                              limit: int = 25,
                              filter: Optional[str] = None):
    logger.info("--- TOOL USED: list_workflow_tasks ---")
    params: dict = {"start": start, "limit": limit}
    if only_workable:
        params["includeOnlyWorkableTasks"] = "true"
    if filter:
        params["filter"] = filter
    data = await vi_request("GET", "workflows", "/processes/tasks",
                            params=params, headers=_WF_HEADERS)
    items, count = _collection_items(data)
    return compact({
        "count": count if count is not None else len(items),
        "tasks": [_shape_task(t) for t in items],
    })


@vi.add(
    "get_workflow_task",
    "Get one workflow task in full, including the actions available to "
    "complete it — call this before complete_workflow_task to see the "
    "valid action names.",
    {"type": "object", "properties": {"task_id": {"type": "string"}},
     "required": ["task_id"]},
)
async def get_workflow_task(task_id: str):
    logger.info("--- TOOL USED: get_workflow_task ---")
    return compact(await vi_request(
        "GET", "workflows", f"/processes/tasks/tasks/{task_id}",
        headers=_WF_HEADERS))


@vi.add(
    "list_workflow_processes",
    "List investigation workflow processes (one per entity under "
    "investigation), active ones by default.",
    {"type": "object",
     "properties": {
         "active_only": {"type": "boolean", "description": "Default true."},
         "start": {"type": "integer"},
         "limit": {"type": "integer"}},
     },
)
async def list_workflow_processes(active_only: bool = True, start: int = 0,
                                  limit: int = 25):
    logger.info("--- TOOL USED: list_workflow_processes ---")
    path = "/processes/actives" if active_only else "/processes"
    data = await vi_request("GET", "workflows", path,
                            params={"start": start, "limit": limit},
                            headers=_WF_HEADERS)
    items, count = _collection_items(data)
    return compact({
        "count": count if count is not None else len(items),
        "processes": [_shape_process(p) for p in items],
    })


@vi.add(
    "complete_workflow_task",
    "Complete a workflow task with one of its available actions (get the "
    "valid names/ids from get_workflow_task first). This advances a real "
    "investigation — requires VI_ALLOW_ACTIONS=true and explicit user "
    "confirmation.",
    {"type": "object",
     "properties": {
         "task_id": {"type": "string"},
         "action_name": {"type": "string"},
         "action_id": {"type": "string", "description": "Optional action ID."}},
     "required": ["task_id", "action_name"]},
)
async def complete_workflow_task(task_id: str, action_name: str,
                                 action_id: Optional[str] = None):
    logger.info("--- TOOL USED: complete_workflow_task ---")
    _require_actions_enabled("complete_workflow_task")
    body: dict = {"name": action_name}
    if action_id:
        body["id"] = action_id
    data = await vi_request(
        "PUT", "workflows", f"/processes/tasks/tasks/{task_id}/completed",
        body=body, content_type=_WF_ACTION_CT, headers=_WF_HEADERS)
    return compact({"taskId": task_id, "action": action_name,
                    "result": data})


# ── escape hatch ────────────────────────────────────────────────────


@vi.add(
    "vi_api_request",
    "Generic Visual Investigator REST call — the exploration escape hatch "
    "when no dedicated tool covers an endpoint. `service` is one of alert, "
    "datahub, sand, workflows; `path` is relative to that service (e.g. "
    "service='alert', path='/alerts'). GET is always allowed; POST and PUT "
    "require VI_ALLOW_ACTIONS=true and are only for search-style or "
    "explicitly user-confirmed calls. Never guess destructive endpoints.",
    {"type": "object",
     "properties": {
         "method": {"type": "string", "enum": ["GET", "POST", "PUT"]},
         "service": {"type": "string",
                     "enum": ["alert", "datahub", "sand", "workflows"]},
         "path": {"type": "string", "description": "Path relative to the service, e.g. /alerts."},
         "params": {"type": "object", "description": "Optional query parameters."},
         "body": {"type": "object", "description": "Optional JSON body for POST/PUT."}},
     "required": ["method", "service", "path"]},
)
async def vi_api_request(method: str, service: str, path: str,
                         params: Optional[dict] = None,
                         body: Optional[dict] = None):
    logger.info("--- TOOL USED: vi_api_request (%s %s %s) ---",
                method, service, path)
    method = (method or "GET").upper()
    if method not in ("GET", "POST", "PUT"):
        raise ToolError("method must be GET, POST, or PUT.")
    if method != "GET":
        _require_actions_enabled(f"vi_api_request {method}")
    data = await vi_request(method, service, path, params=params, body=body)
    return compact({"service": service, "path": path, "data": data})
