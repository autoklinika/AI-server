"""Benchmark-only router adapters.

These adapters do not participate in production routing. They provide stable
subjects for the decision-model benchmark.
"""
from __future__ import annotations

import hashlib
import json
import platform
import re
import time
import urllib.request
from pathlib import Path

from .contracts import GoldenCase
from .runner import RouterDecision


class MajorityKnowledgeRouterAdapter:
    """Dataset-independent majority-class floor for router evaluation."""

    adapter_id = "majority-knowledge-v1"

    def decide(self, case: GoldenCase) -> RouterDecision:
        started = time.perf_counter()
        return RouterDecision(
            route="knowledge_rag",
            selected_tools=["knowledge.search"],
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )


class RulesV1RouterAdapter:
    """Pipeline sanity adapter; not a valid generalization baseline."""

    adapter_id = "rules-v1"

    _vision = re.compile(
        r"\b(zdję|zdjec|image|photo|fot[oę]|pcb|odczytaj oznaczenie)\w*",
        re.IGNORECASE,
    )
    _graph = re.compile(
        r"\b(graf|graph|dependency|zależno|upstream failure)\w*",
        re.IGNORECASE,
    )
    _telemetry = re.compile(
        r"\b(aktualn|current|live|pracując|running)\w*.*"
        r"(temperatur|pressure|ciśn|rail|rpm|obrot|telemetr)",
        re.IGNORECASE | re.DOTALL,
    )
    _agent = re.compile(
        r"\b(agent\w*\s+ers|agenta\s+ers|przekaż\w*.*ers|new case|nowego case)",
        re.IGNORECASE | re.DOTALL,
    )
    _measurement_reasoning = re.compile(
        r"\b(v|volt|rail|reset|napię|pulsuj|spada)\w*",
        re.IGNORECASE,
    )

    def decide(self, case: GoldenCase) -> RouterDecision:
        started = time.perf_counter()
        query = case.question

        if self._agent.search(query):
            route, tools = "tool", ["agent.ers"]
        elif self._graph.search(query):
            route, tools = "graphify", ["graphify.query", "knowledge.search"]
        elif self._vision.search(query):
            tools = ["vision.analyze"]
            if re.search(r"\bknowledge\b|wiedzy|funkcj|fault mode", query, re.IGNORECASE):
                tools.append("knowledge.search")
            route = "vision"
        elif self._telemetry.search(query):
            route, tools = "telemetry", ["telemetry.read"]
        elif self._measurement_reasoning.search(query) and re.search(
            r"który blok|sprawdzać najpierw|why|dlaczego", query, re.IGNORECASE
        ):
            route, tools = "reasoning", []
        else:
            route, tools = "knowledge_rag", ["knowledge.search"]

        return RouterDecision(
            route=route,
            selected_tools=tools,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )


ROUTE_LABELS = {
    "knowledge_rag": "Retrieve facts from the internal technical knowledge base or RAG.",
    "graphify": "Build or query a dependency or relationship graph.",
    "telemetry": "Read current or live telemetry, sensor values, or operating data.",
    "vision": "Analyze an image, photograph, PCB, or other visual input.",
    "reasoning": "Reason from measurements and facts already supplied without retrieval.",
    "tool": "Hand off to a specialized agent or execute an operational tool action.",
}

TOOL_LABELS = {
    "knowledge.search": "Search the internal technical knowledge base.",
    "graphify.query": "Query or build a dependency graph.",
    "telemetry.read": "Read current live telemetry.",
    "vision.analyze": "Analyze an image or PCB visually.",
    "agent.ers": "Hand the repair case to the ECU Repair Service agent.",
}

SYSTEM_ONE_TOOL_KEYS = {
    "knowledge.search": "tool_knowledge_search",
    "graphify.query": "tool_graphify_query",
    "telemetry.read": "tool_telemetry_read",
    "vision.analyze": "tool_vision_analyze",
    "agent.ers": "tool_agent_ers",
}


class OllamaSystemOneRouterAdapter:
    """Ollama 0.35+ System One decision-model router benchmark adapter."""

    adapter_id = "ollama-systemone-v1"

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "http://127.0.0.1:11434",
        tool_threshold: float = 0.5,
        timeout_seconds: float = 120.0,
        requester=None,
    ) -> None:
        if not model:
            raise ValueError("System One model is required")
        if not 0.0 <= tool_threshold <= 1.0:
            raise ValueError("tool_threshold must be between 0 and 1")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.tool_threshold = tool_threshold
        self.timeout_seconds = timeout_seconds
        self._requester = requester or self._request

    def _json(self, path: str) -> dict:
        request = urllib.request.Request(self.base_url + path)
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.load(response)

    def _request(self, payload: dict) -> dict:
        request = urllib.request.Request(
            self.base_url + "/v1/systemone",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.load(response)

    def runtime_metadata(self) -> dict:
        version = self._json("/api/version")
        tags = self._json("/api/tags").get("models", [])
        def matches(item: dict) -> bool:
            names = {str(item.get("name", "")), str(item.get("model", ""))}
            return (
                self.model in names
                or (
                    ":" not in self.model
                    and any(name.split(":", 1)[0] == self.model for name in names)
                )
            )

        model = next((item for item in tags if matches(item)), None)
        if model is None:
            raise ValueError(f"System One model not installed: {self.model}")
        return {
            "ollama_api_version": str(version.get("version", "")),
            "model": self.model,
            "model_digest": str(model.get("digest", "")),
            "model_size_bytes": str(model.get("size", "")),
            "system_one_endpoint": "/v1/systemone",
        }

    @staticmethod
    def _tool_enabled(answer: dict, threshold: float) -> bool:
        value = answer.get("noul")
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return float(value) >= threshold
        raise ValueError(f"invalid System One noul answer: {value!r}")

    def decide(self, case: GoldenCase) -> RouterDecision:
        questions = {
            "route": {
                "type": "choice",
                "instructions": (
                    "Choose exactly one primary AI Platform route for this user request."
                ),
                "criteria": ROUTE_LABELS,
            }
        }
        for tool, key in SYSTEM_ONE_TOOL_KEYS.items():
            questions[key] = {
                "type": "noul",
                "instructions": (
                    f"Does this request require the {tool} tool? "
                    "Answer true only when the tool is necessary to fulfill the request."
                ),
                "criteria": {
                    "true": TOOL_LABELS[tool],
                    "false": f"Do not invoke {tool}.",
                },
            }

        started = time.perf_counter()
        result = self._requester({
            "model": self.model,
            "state": case.question,
            "questions": questions,
            "keep_alive": "30m",
        })
        latency_ms = (time.perf_counter() - started) * 1000.0
        answers = result.get("answers")
        if not isinstance(answers, dict):
            raise ValueError("System One response missing answers")
        route_answer = answers.get("route")
        if not isinstance(route_answer, dict):
            raise ValueError("System One response missing route")
        route = route_answer.get("choice")
        if route not in ROUTE_LABELS:
            raise ValueError(f"invalid System One route output: {route!r}")

        tools = []
        for tool, key in SYSTEM_ONE_TOOL_KEYS.items():
            answer = answers.get(key)
            if not isinstance(answer, dict):
                raise ValueError(f"System One response missing tool answer: {key}")
            if self._tool_enabled(answer, self.tool_threshold):
                tools.append(tool)

        return RouterDecision(
            route=route,
            selected_tools=tools,
            latency_ms=latency_ms,
        )


class Gliner2RouterAdapter:
    """Zero-shot GLiNER2 route + multi-tool classifier."""

    adapter_id = "gliner2-v1"

    def __init__(
        self,
        checkpoint: str,
        *,
        revision: str | None = None,
        threshold: float = 0.5,
        head_mode: str = "joint",
        extractor=None,
    ) -> None:
        if not 0.0 < threshold < 1.0:
            raise ValueError("threshold must be between 0 and 1")
        if head_mode not in {"joint", "separate"}:
            raise ValueError("head_mode must be joint or separate")
        self.checkpoint = checkpoint
        self.revision = revision
        self.threshold = threshold
        self.head_mode = head_mode
        if extractor is None:
            try:
                from gliner2 import AutoExtractor
            except ImportError as exc:
                raise RuntimeError(
                    "GLiNER2 local runtime is not installed in this environment"
                ) from exc
            extractor = AutoExtractor.from_pretrained(
                checkpoint,
                revision=revision,
                map_location="cpu",
            )
        self.extractor = extractor

    def runtime_metadata(self) -> dict[str, str]:
        import gliner2
        import gliner2.models.base
        import torch

        base_path = Path(gliner2.models.base.__file__).resolve()
        return {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "gliner2": getattr(gliner2, "__version__", "unknown"),
            "gliner2_base_sha256": hashlib.sha256(base_path.read_bytes()).hexdigest(),
        }

    def decide(self, case: GoldenCase) -> RouterDecision:
        import resource

        started = time.perf_counter()
        route_schema = {"route": {"labels": ROUTE_LABELS}}
        tools_schema = {
            "tools": {
                "labels": TOOL_LABELS,
                "multi_label": True,
                "cls_threshold": self.threshold,
            }
        }
        if self.head_mode == "joint":
            result = self.extractor.classify_text(
                case.question,
                {**route_schema, **tools_schema},
            )
            route = result.get("route")
            tools = result.get("tools", [])
        else:
            route = self.extractor.classify_text(
                case.question, route_schema
            ).get("route")
            tools = self.extractor.classify_text(
                case.question, tools_schema
            ).get("tools", [])
        latency_ms = (time.perf_counter() - started) * 1000.0
        if route not in ROUTE_LABELS:
            raise ValueError(f"invalid GLiNER2 route output: {route!r}")
        if isinstance(tools, str):
            tools = [tools]
        if not isinstance(tools, list) or any(tool not in TOOL_LABELS for tool in tools):
            raise ValueError(f"invalid GLiNER2 tool output: {tools!r}")
        peak_ram_bytes = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
        return RouterDecision(
            route=route,
            selected_tools=tools,
            latency_ms=latency_ms,
            peak_ram_bytes=peak_ram_bytes,
        )
