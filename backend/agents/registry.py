"""The SAS demo agent line-up and the SAS Copilot's specialist sub-agents.

Each agent is a system prompt + one or more toolsets (optionally a subset of
each). The SAS Viya Copilot additionally carries a specialist roster the
runner exposes through a delegate_to_specialist tool — sub-agents run their
own tool loop and report back, and their steps appear in the same trace.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sasviya.tools import viya
from sasvi.tools import vi
from websearch.tools import web
from usecase.tools import procurement
from frontline.tools import frontline
from toolset import ToolSet, charts

from . import prompts


@dataclass
class AgentDef:
    id: str
    name: str
    description: str
    system: str
    # list of (toolset, subset-of-tool-names | None for all)
    toolsets: list = field(default_factory=list)
    specialists: dict = field(default_factory=dict)   # id -> AgentDef
    max_iters: int = 14
    # starter prompts shown as chips on a fresh conversation, per language
    suggestions: dict = field(default_factory=dict)   # {"en": [...], "ar": [...]}

    def tool_specs(self) -> list[dict]:
        specs = []
        for ts, subset in self.toolsets:
            specs.extend(ts.specs(subset))
        return specs

    def find_toolset(self, tool_name: str) -> Optional[ToolSet]:
        for ts, subset in self.toolsets:
            names = subset if subset is not None else ts.tool_names
            if tool_name in names and ts.has(tool_name):
                return ts
        return None


# ── SAS Viya Copilot: the official MCP's 9 tiers as an agent team ───
# Every tool below is one of the official SAS Viya MCP Server's 74 tools
# (tiers 0-7, bridged in-process by sasviya/tools.py — see
# backend/sas_mcp_server/). No custom tools: the copilot is a multi-agent
# harness over the official server, nothing more. Each specialist owns
# the tiers of one stage of the analytics lifecycle (plus the discovery
# tools it needs for grounding); together they cover all 74.

_CAS_GROUNDING = ["list_caslibs", "list_castables", "get_castable_info",
                  "get_castable_columns", "get_castable_data"]

SPECIALISTS = {
    "sas_programmer": AgentDef(
        id="sas_programmer", name="SAS Programmer",
        description="Writes and runs SAS code in compute sessions (Tier 0) and manages "
                    "long-running batch jobs (Tier 4) — data steps, PROCs, SQL, job logs.",
        system=prompts.SAS_PROGRAMMER,
        toolsets=[(viya, ["execute_sas_code", "list_compute_contexts",
                          "reset_compute_session",
                          "submit_batch_job", "get_job_status", "get_job_log",
                          "list_jobs", "cancel_job",
                          "list_compute_libraries", "list_compute_tables",
                          "list_compute_columns"])],
        max_iters=12),
    "data_explorer": AgentDef(
        id="data_explorer", name="Data Explorer",
        description="Owns Data Discovery (Tier 1): the Information Catalog (search, "
                    "profiles, catalog agents), CAS and compute metadata, and deep "
                    "column-level data profiling.",
        system=prompts.DATA_EXPLORER,
        toolsets=[(viya, ["catalog_search", "catalog_search_helper",
                          "catalog_find_instance", "catalog_list_agents",
                          "catalog_get_agent_history", "catalog_run_agent",
                          "catalog_run_adhoc_analysis", "catalog_get_adhoc_analysis",
                          "catalog_download_table_profile",
                          "list_compute_libraries", "list_compute_tables",
                          "list_compute_columns", "list_cas_servers",
                          "list_source_tables", "execute_sas_code"]
                         + _CAS_GROUNDING)],
        max_iters=12),
    "data_engineer": AgentDef(
        id="data_engineer", name="Data Engineer",
        description="Owns Data Operations & Files (Tier 2): uploads CSV/Excel/inline "
                    "data, manages files, loads and promotes CAS tables, prepares and "
                    "generates data with SAS code.",
        system=prompts.DATA_ENGINEER,
        toolsets=[(viya, ["upload_data", "upload_inline_data", "upload_file",
                          "download_file", "list_files",
                          "promote_table_to_memory", "list_source_tables",
                          "execute_sas_code"] + _CAS_GROUNDING)],
        max_iters=12),
    "report_designer": AgentDef(
        id="report_designer", name="Report Designer",
        description="Owns Reports & Visualization (Tier 3): finds, reads, creates, "
                    "edits, copies, and exports SAS Visual Analytics reports.",
        system=prompts.REPORT_DESIGNER,
        toolsets=[(viya, ["list_reports", "get_report", "get_report_outline",
                          "describe_report_objects", "create_report",
                          "copy_report", "apply_report_operations",
                          "export_report", "delete_report",
                          "list_castables", "get_castable_columns",
                          "get_castable_data"])],
        max_iters=12),
    "ml_builder": AgentDef(
        id="ml_builder", name="ML Builder",
        description="Owns Automated Machine Learning (Tier 5): AutoML projects end to "
                    "end — create, run, monitor, and register/publish the champion model.",
        system=prompts.ML_BUILDER,
        toolsets=[(viya, ["list_ml_projects", "create_ml_project", "run_ml_project",
                          "register_ml_champion_model", "publish_ml_champion_model",
                          "list_publishing_destinations", "promote_table_to_memory",
                          "list_castables", "get_castable_info",
                          "get_castable_columns", "execute_sas_code"])],
        max_iters=12),
    "model_ops": AgentDef(
        id="model_ops", name="Model Ops",
        description="Owns Model Management & Scoring (Tier 6): the model repository, "
                    "publishing destinations, MAS modules, and real-time scoring.",
        system=prompts.MODEL_OPS,
        toolsets=[(viya, ["list_registered_models", "list_publishing_destinations",
                          "list_mas_modules", "get_mas_module_step_signature",
                          "score_data", "list_ml_projects",
                          "register_ml_champion_model",
                          "publish_ml_champion_model"])],
        max_iters=12),
    "decision_architect": AgentDef(
        id="decision_architect", name="Decision Architect",
        description="Owns SAS Intelligent Decisioning (Tier 7): business rule sets and "
                    "rules, decision flows, revision locking, publishing to MAS, and "
                    "live decision testing.",
        system=prompts.DECISION_ARCHITECT,
        toolsets=[(viya, ["list_business_rulesets", "create_business_ruleset",
                          "get_business_ruleset", "update_business_ruleset",
                          "delete_business_ruleset",
                          "lock_business_ruleset_revision",
                          "list_business_ruleset_revisions",
                          "create_business_rule", "update_business_rule",
                          "get_business_rule", "list_business_rules",
                          "delete_business_rule",
                          "create_decision_flow", "update_decision_flow",
                          "get_decision_flow", "list_decision_flows",
                          "delete_decision_flow", "get_decision_flow_code",
                          "lock_decision_flow_revision",
                          "list_decision_flow_revisions",
                          "get_decision_flow_revision", "publish_decision_flow",
                          "list_mas_modules", "get_mas_module_step_signature",
                          "score_data"])],
        max_iters=14),
}

# The copilot's own hands: fast lookups and one-shot answers across every
# tier, so simple questions never need a delegation round-trip. Heavy,
# multi-step work goes to the specialist that owns the tier.
_COPILOT_CORE = ["catalog_search", "list_cas_servers", "list_caslibs",
                 "list_castables", "get_castable_info", "get_castable_columns",
                 "get_castable_data", "execute_sas_code", "list_files",
                 "list_jobs", "list_reports", "list_ml_projects",
                 "list_registered_models", "list_publishing_destinations",
                 "list_mas_modules", "get_mas_module_step_signature",
                 "score_data", "list_decision_flows", "list_business_rulesets"]


# ── The public agents ───────────────────────────────────────────────

AGENTS: dict[str, AgentDef] = {
    "sas-copilot": AgentDef(
        id="sas-copilot",
        name="SAS Viya Copilot",
        description="The complete SAS Viya platform in one copilot — the official "
                    "SAS Viya MCP Server (74 tools across 9 tiers) driven by a "
                    "specialist agent team: code, discovery, data ops, reports, "
                    "AutoML, model ops, and intelligent decisioning.",
        system=prompts.SAS_COPILOT,
        toolsets=[(viya, _COPILOT_CORE)],
        specialists=SPECIALISTS,
        max_iters=18,
        suggestions={
            "en": [
                "What data do we have? Give me a quick tour of the environment.",
                "Profile the most interesting table end to end and tell me what needs attention.",
                "Build a model with AutoML, publish the champion, and score one record in real time.",
                "Create a supplier-risk rule set and decision flow, publish it, and test a decision.",
            ],
            "ar": [
                "ما البيانات المتوفرة لدينا؟ قدّم لي جولة سريعة في البيئة.",
                "حلّل أهم جدول من البداية إلى النهاية وأخبرني بما يستحق الانتباه.",
                "ابنِ نموذجاً بالتعلّم الآلي وانشر النموذج البطل واحسب درجة سجل واحد فورياً.",
                "أنشئ مجموعة قواعد وتدفق قرار لمخاطر الموردين وانشره واختبر قراراً.",
            ],
        }),
    "vi-investigator": AgentDef(
        id="vi-investigator",
        name="Investigation Assistant (Visual Investigator)",
        description="Triage copilot for SAS Visual Investigator — work the alert "
                    "queue, explain detections, flag false positives, recommend actions.",
        system=prompts.VI_AGENT,
        toolsets=[(vi, None), (charts, None)],
        max_iters=14,
        suggestions={
            "en": [
                "What should I look at first today?",
                "Triage the highest-priority alert — why did it fire?",
                "Could this alert be a false positive? Walk me through the evidence.",
                "Who is connected to this supplier, and through what?",
            ],
            "ar": [
                "بماذا أبدأ اليوم؟",
                "افرز التنبيه الأعلى أولوية — لماذا انطلق؟",
                "هل يمكن أن يكون هذا التنبيه إنذاراً كاذباً؟ اشرح لي الأدلة.",
                "من يرتبط بهذا المورد وبأي روابط؟",
            ],
        }),
    "procurement-analyst": AgentDef(
        id="procurement-analyst",
        name="Procurement Integrity Analyst",
        description="Use-case agent over government procurement data — tenders, "
                    "suppliers, invoices, red-flag alerts, and ready risk models.",
        system=prompts.PROCUREMENT_AGENT,
        toolsets=[(procurement, None), (charts, None)],
        max_iters=12,
        suggestions={
            "en": [
                "Who are our riskiest suppliers right now?",
                "Run the bid-rigging screen on IT tenders.",
                "How much are we overpaying versus market prices?",
                "Any purchases split to stay under the approval threshold?",
            ],
            "ar": [
                "من هم الموردون الأعلى خطورة حالياً؟",
                "شغّل فحص التواطؤ في عطاءات تقنية المعلومات.",
                "كم ندفع زيادة عن أسعار السوق؟",
                "هل هناك مشتريات مجزّأة للبقاء تحت حد الاعتماد؟",
            ],
        }),
    "global-intel": AgentDef(
        id="global-intel",
        name="Global Intelligence (Web Search)",
        description="Scans news and the web — what other countries are doing, "
                    "emerging technologies, and trends that matter to the organization.",
        system=prompts.WEB_AGENT,
        toolsets=[(web, None), (charts, None)],
        max_iters=12,
        suggestions={
            "en": [
                "What are other countries doing on AI-driven procurement oversight?",
                "What changed in agentic AI this month?",
                "Best practice for supplier risk monitoring — summarize with sources.",
                "How are governments using AI copilots? Give examples, with sources.",
            ],
            "ar": [
                "ماذا تفعل الدول الأخرى في الرقابة على المشتريات بالذكاء الاصطناعي؟",
                "ما الجديد في الذكاء الاصطناعي الوكيل هذا الشهر؟",
                "لخّص أفضل الممارسات في مراقبة مخاطر الموردين مع المصادر.",
                "كيف تستخدم الحكومات المساعدات الذكية؟ أعطني أمثلة مع المصادر.",
            ],
        }),
}


# ── Frontline Assist (social benefits) ──────────────────────────────

_INTEGRATIONS = ["get_beneficiary_profile", "check_icp", "check_mohre",
                 "check_gpssa", "check_card_status", "check_utility"]

FRONTLINE_SPECIALISTS = {
    "knowledge_decision": AgentDef(
        id="knowledge_decision", name="Knowledge & Decision AI Agent",
        description="Analytical backbone — verifies facts across the integrations and runs the deterministic Smart Form engine; evidence-based reports.",
        system=prompts.KNOWLEDGE_DECISION,
        toolsets=[(frontline, _INTEGRATIONS + ["evaluate_complaint"])],
        max_iters=10),
    "document_processing": AgentDef(
        id="document_processing", name="Document Processing AI Agent",
        description="Shared document service — submits uploads to the existing document-intelligence module (IDP) and consumes confidence scores, extracted fields, and rejection reasons.",
        system=prompts.DOCUMENT_PROCESSING,
        toolsets=[(frontline, ["submit_document_to_idp"])],
        max_iters=6),
}

AGENTS["customer-resolution"] = AgentDef(
    id="customer-resolution",
    name="Customer Resolution Agent",
    description="Frontline Assist — resolves Inflation Allowance and SWP "
                "complaints end to end: real-time integration checks, a "
                "deterministic Smart Form decision engine (eight outcomes), "
                "and an AI-document fallback when systems are unavailable.",
    system=prompts.CUSTOMER_RESOLUTION,
    toolsets=[(frontline, None), (charts, None)],
    specialists=FRONTLINE_SPECIALISTS,
    max_iters=14,
    suggestions={
        "en": [
            "I didn't receive my Inflation Allowance this month. My Emirates ID is 784-1990-7654321-3.",
            "My payment card never arrived — ID 784-1978-1122334-5.",
            "Why was my application rejected? ID 784-1995-4455667-8.",
            "The allowance amount looks wrong this month — ID 784-1969-9988776-1.",
        ],
        "ar": [
            "لم أستلم علاوة التضخم هذا الشهر. رقم هويتي 784-1990-7654321-3.",
            "بطاقة الدفع لم تصلني — الهوية 784-1978-1122334-5.",
            "لماذا رُفض طلبي؟ الهوية 784-1995-4455667-8.",
            "مبلغ العلاوة يبدو خاطئاً هذا الشهر — الهوية 784-1969-9988776-1.",
        ],
    })

AGENTS["case-management"] = AgentDef(
    id="case-management",
    name="Case Management Agent",
    description="Supervisor view over the Frontline Assist case queue — SLA "
                "breaches, case timelines with the full inter-agent audit "
                "trail, and queue analytics.",
    system=prompts.CASE_MANAGEMENT,
    toolsets=[(frontline, ["list_cases", "get_case_timeline",
                           "get_beneficiary_profile"]),
              (charts, None)],
    specialists=FRONTLINE_SPECIALISTS,
    max_iters=12,
    suggestions={
        "en": [
            "What's in the case queue today? Anything breaching SLA?",
            "Show me the full timeline for case FA-2026-0142.",
            "Chart open cases by outcome and status.",
        ],
        "ar": [
            "ما الموجود في قائمة الحالات اليوم؟ هل هناك تجاوز لاتفاقية مستوى الخدمة؟",
            "اعرض السجل الكامل للحالة FA-2026-0142.",
            "ارسم الحالات المفتوحة حسب النتيجة والحالة.",
        ],
    })



def get_agent(agent_id: str) -> Optional[AgentDef]:
    return AGENTS.get(agent_id)


def list_agents() -> list[dict]:
    return [{"id": a.id, "name": a.name, "description": a.description,
             "suggestions": a.suggestions}
            for a in AGENTS.values()]
