"""GLiNER2.5 decision-model adapter for the independent router suite."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .contracts import GoldenCase
from .runner import RouterDecision


ROUTE_LABELS = [
    "reasoning",
    "knowledge_rag",
    "graphify",
    "telemetry",
    "vision",
    "tool",
]

TOOL_LABELS = [
    "knowledge.search",
    "graphify.query",
    "vision.analyze",
    "agent.ers",
    "telemetry.read",
    "none",
]


def _process_peak_rss_bytes() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _single(value: Any, key: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for candidate in ("label", "category", "value"):
            if isinstance(value.get(candidate), str):
                return value[candidate]
    raise ValueError(f"GLiNER result {key!r} is not a single label")


def _multi(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        labels = []
        for item in value:
            labels.append(_single(item, key) if isinstance(item, dict) else str(item))
        return labels
    if isinstance(value, dict):
        nested = value.get("labels") or value.get("values")
        if nested is not None:
            return _multi(nested, key)
    raise ValueError(f"GLiNER result {key!r} is not a multi-label value")


def _case_text(case: GoldenCase) -> str:
    history = [
        f"{turn.role.upper()}: {turn.content}"
        for turn in case.context_turns
    ]
    history.append(f"USER: {case.question}")
    return "\n".join(history)


class GlinerDecisionAdapter:
    def __init__(
        self,
        model_id: str,
        *,
        extractor=None,
        map_location: str = "cpu",
        tool_threshold: float = 0.4,
    ):
        self.model_id = model_id
        self.extractor = extractor
        self.map_location = map_location
        self.tool_threshold = tool_threshold

    def _load(self):
        if self.extractor is None:
            try:
                from gliner2 import AutoExtractor
            except ImportError as exc:
                raise RuntimeError(
                    "GLiNER2 local runtime is not installed; install optional "
                    "router benchmark dependencies before a live router run"
                ) from exc
            self.extractor = AutoExtractor.from_pretrained(
                self.model_id,
                map_location=self.map_location,
            )
        return self.extractor

    def decide(self, case: GoldenCase) -> RouterDecision:
        extractor = self._load()
        started = time.perf_counter()
        result = extractor.classify_text(
            _case_text(case),
            {
                "route": ROUTE_LABELS,
                "tools": {
                    "labels": TOOL_LABELS,
                    "multi_label": True,
                    "cls_threshold": self.tool_threshold,
                },
            },
        )

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if not isinstance(result, dict):
            raise ValueError("GLiNER classify_text returned non-object result")
        route = _single(result.get("route"), "route")
        if route not in ROUTE_LABELS:
            raise ValueError(f"GLiNER returned unsupported route {route!r}")
        tools = [
            tool for tool in _multi(result.get("tools"), "tools")
            if tool != "none"
        ]
        unknown = sorted(set(tools) - set(TOOL_LABELS))
        if unknown:
            raise ValueError(f"GLiNER returned unsupported tools {unknown}")
        return RouterDecision(
            route=route,
            selected_tools=tools,
            latency_ms=elapsed_ms,
            peak_ram_bytes=_process_peak_rss_bytes(),
        )
