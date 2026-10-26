"""Read-only Granite decision router contract. Never executes selected tool names.

The contract is stable independently of the local model, prompt or serving runtime.
Only use accepted decisions as routing *suggestions*, not as permissions to act.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

ROUTE_TO_TOOLS = {
    "knowledge_rag": ["knowledge.search"],
    "reasoning": [],
    "telemetry": ["telemetry.read"],
    "graphify": ["graphify.query"],
    "vision": ["vision.analyze"],
    "tool": ["agent.ers"],
}
FALLBACK_CAPABILITIES = {
    "web.search", "github.read", "github.write", "host.inspect",
    "general_llm", "other",
}
DECISIONS = {"route", "clarify", "fallback", "no_action"}
SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|bearer[ :]|api[_ -]?key|access[_ -]?token|"
    r"BEGIN [A-Z ]*PRIVATE KEY|ssh-rsa|ssh-ed25519)"
)

# Ollama's 'format' schema is an output constraint, never an authorization layer.
DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": sorted(DECISIONS)},
        "route": {
            "type": ["string", "null"],
            "enum": sorted(ROUTE_TO_TOOLS) + [None],
        },
        "selected_tools": {
            "type": "array",
            "items": {"type": "string", "enum": sorted({
                value for tools in ROUTE_TO_TOOLS.values() for value in tools
            })},
            "maxItems": 1,
        },
        "required_capability": {
            "type": ["string", "null"],
            "enum": sorted(FALLBACK_CAPABILITIES) + [None],
        },
    },
    "required": ["decision", "route", "selected_tools", "required_capability"],
    "additionalProperties": False,
}

ROUTER_PROMPT = 'You are Granite, a strict intent-and-capability router for the local AI Platform.\nThe input is the current user request only. Do not invent previous context, documents, device states, or permissions.\nReturn exactly one valid compact JSON object, no markdown, no explanation, with keys in this order:\n{"decision":"route|clarify|fallback|no_action","route":null,"selected_tools":[],"required_capability":null}\n\nRules:\n- decision=route only for a self-contained request supported by exactly one local route:\n  knowledge_rag -> ["knowledge.search"] for facts that must be looked up in internal documents.\n  reasoning -> [] for reasoning/design using facts given in the request without a missing external source.\n  telemetry -> ["telemetry.read"] for live telemetry already exposed by the platform.\n  graphify -> ["graphify.query"] only for graph relationship traversal.\n  vision -> ["vision.analyze"] only when the user requires actual image analysis.\n  tool -> ["agent.ers"] only for a clearly defined ERS-domain agent operation, NEVER for GitHub, terminal, host administration or other unsupported tools.\n  For decision=route set required_capability=null.\n- decision=clarify and route=null and selected_tools=[] and required_capability=null when a crucial referent, parameter, attachment or previous turn is missing. Do not guess what "it", "that", "the second one", or "do the same" means.\n- decision=fallback and route=null and selected_tools=[] for a request needing a capability outside the six local routes. Set required_capability to exactly one from ["web.search","github.read","github.write","host.inspect","general_llm","other"]. This is ONLY a routing recommendation, never execution or permission.\n- decision=no_action and route=null and selected_tools=[] and required_capability=null for an acknowledgement, closing remark, statement, or explicit "do nothing" with no new task.\n- If external current information is needed, use fallback/web.search, not reasoning or knowledge_rag.\n- Do not choose a tool just because the question is technical, and do not attempt to execute actions.\nClassify Polish and English equally. Output strict JSON only.\n'

class RouterContractError(ValueError):
    """Rejected model output or unsafe input; never include user's text in errors."""


def validate_input(text: str) -> None:
    if (not isinstance(text, str) or not 1 <= len(text) <= 1400 or not text.strip()
            or len(text.encode("utf-8")) > 2400 or "\x00" in text
            or SECRET_PATTERN.search(text)):
        raise RouterContractError("router_input_rejected")


@dataclass(frozen=True, slots=True)
class RouterDecision:
    decision: Literal["route", "clarify", "fallback", "no_action"]
    route: str | None
    selected_tools: tuple[str, ...]
    required_capability: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "route": self.route,
            "selected_tools": list(self.selected_tools),
            "required_capability": self.required_capability,
        }


def parse_router_decision(raw: str | dict) -> RouterDecision:
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, ValueError, TypeError):
        raise RouterContractError("router_invalid_json") from None
    if not isinstance(payload, dict) or set(payload) != {
        "decision", "route", "selected_tools", "required_capability"
    }:
        raise RouterContractError("router_schema_mismatch")
    decision = payload["decision"]
    route = payload["route"]
    tools = payload["selected_tools"]
    capability = payload["required_capability"]
    if type(decision) is not str or decision not in DECISIONS:
        raise RouterContractError("router_invalid_decision")
    if type(tools) is not list or any(type(tool) is not str for tool in tools):
        raise RouterContractError("router_invalid_tools")
    if decision == "route":
        if (type(route) is not str or route not in ROUTE_TO_TOOLS
                or tools != ROUTE_TO_TOOLS[route]
                or capability is not None):
            raise RouterContractError("router_invalid_local_route")
    else:
        if route is not None or tools:
            raise RouterContractError("router_nonroute_tool_forbidden")
        if decision == "fallback":
            if type(capability) is not str or capability not in FALLBACK_CAPABILITIES:
                raise RouterContractError("router_invalid_capability")
        elif capability is not None:
            raise RouterContractError("router_unexpected_capability")
    return RouterDecision(decision, route, tuple(tools), capability)
