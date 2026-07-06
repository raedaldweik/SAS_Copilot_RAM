"""Push the bundled procurement-integrity use case into SAS Viya.

Creates (or refreshes) CAS tables in a caslib — the raw datasets plus the
scored model outputs — so the use case lives on the platform: queryable with
CAS SQL, chartable in Visual Analytics, and usable as AutoML training data.
"""
from __future__ import annotations

import logging

import pandas as pd

from toolset import ToolError
from sasviya import config as viya_config
from sasviya.tools import execute_sas_code, upload_data, promote_table_to_memory

from .data import get_data
from .models import supplier_risk, bid_rigging, price_anomaly

logger = logging.getLogger(__name__)


def _frames() -> dict[str, pd.DataFrame]:
    d = get_data()
    frames = {
        "PROC_SUPPLIERS": d["suppliers"],
        "PROC_TENDERS": d["tenders"],
        "PROC_BIDS": d["bids"],
        "PROC_INVOICES": d["invoices"],
        "PROC_ALERTS": d["alerts"],
    }

    # scored model outputs — so "the models" live on the platform too
    sr = supplier_risk(view="top_suppliers", n=100_000)
    frames["PROC_SUPPLIER_RISK"] = pd.DataFrame(sr["rows"])

    clusters = []
    for c in bid_rigging().get("clusters", []):
        c = dict(c)
        tw = c.pop("top_winners", [])
        c["top_winners"] = "; ".join(
            f"{w.get('supplier_name')} ({w.get('supplier_id')})"
            for w in tw) if isinstance(tw, list) else str(tw)
        ex = c.pop("example_tenders", [])
        c["example_tenders"] = ("; ".join(map(str, ex))
                                if isinstance(ex, list) else str(ex))
        clusters.append(c)
    frames["PROC_RIG_CLUSTERS"] = pd.DataFrame(clusters)

    pa = price_anomaly(n=100_000)
    frames["PROC_PRICE_ANOMALIES"] = pd.DataFrame(pa.get("top_items", []))
    return frames


async def deploy(caslib: str = "Public",
                 server_id: str = "cas-shared-default") -> dict:
    if not viya_config.configured():
        raise ToolError(
            "SAS Viya is not configured (VIYA_ENDPOINT + credentials) — "
            "cannot deploy the use case. The bundled in-app data keeps "
            "working meanwhile.")

    frames = _frames()
    results: dict = {}

    # drop existing copies so the deploy is repeatable
    drops = "\n".join(
        f'  droptable casdata="{t}" incaslib="{caslib}" quiet;'
        for t in frames)
    try:
        await execute_sas_code(f"proc casutil;\n{drops}\nquit;")
    except Exception as e:  # first-ever deploy, or compute hiccup — not fatal
        logger.warning("pre-drop failed: %s", e)
        results["pre_drop_note"] = str(e)[:200]

    for name, df in frames.items():
        csv = df.to_csv(index=False)
        out = await upload_data(server_id, caslib, name, csv)
        entry = {"rows": int(len(df)), "columns": int(len(df.columns))}
        if isinstance(out, dict):
            entry["status"] = out.get("status")
            if out.get("scope"):
                entry["scope"] = out["scope"]
        results[name] = entry
        try:  # make sure other sessions (VA, SQL) can see it
            await promote_table_to_memory(server_id, caslib, name)
        except Exception:
            pass  # already global — fine

    return {
        "status": "deployed",
        "caslib": caslib,
        "server": server_id,
        "tables": results,
        "next_steps": [
            f"Query with CAS SQL, e.g. SELECT * FROM {caslib}.PROC_SUPPLIER_RISK "
            "ORDER BY risk_score DESC",
            "Build the 'Procurement Integrity Dashboard' in Visual Analytics "
            "on these tables (or map them onto the NCGR template)",
            "Optionally train an AutoML model on PROC_SUPPLIER_RISK "
            "(e.g. target = tier) with the SAS Viya Copilot",
        ],
    }
