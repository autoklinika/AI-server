"""Scheduled WVC analysis policy. An empty telemetry window is a valid skip."""
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class WVCPolicyResult:
    status: str
    reason: str | None
    source_id: str
    window_start: datetime
    window_end: datetime
    analysis: Any = None

    def as_dict(self):
        output = {"status": self.status, "reason": self.reason, "source_id": self.source_id,
                  "window_start": self.window_start.isoformat(), "window_end": self.window_end.isoformat(),
                  "advisory_only": True, "control_actions_supported": False}
        if self.analysis is not None:
            run = self.analysis
            output.update(analysis_id=run.analysis_id, sample_count=run.sample_count, model=run.model,
                          prompt_version=run.prompt_version, reused_existing=run.reused_existing,
                          result=run.result.model_dump(mode="json"))
        return output


class WVCAnalysisPolicy:
    def __init__(self, repository, service):
        self.repository, self.service = repository, service

    def run_window(self, *, source_id, window_start, window_end):
        if window_start.tzinfo is None or window_end.tzinfo is None or window_start >= window_end:
            raise ValueError("analysis requires an ordered timezone-aware window")
        # Serialize the read/reuse/generate/store boundary, including across
        # scheduled processes. The existing unique constraint is a second guard.
        with self.repository.analysis_lock():
            samples = self.repository.load_samples(source_id=source_id, window_start=window_start, window_end=window_end)
            if not samples:
                return WVCPolicyResult("skipped", "no_fresh_data", source_id, window_start, window_end)
            run = self.service.analyze_window(source_id=source_id, window_start=window_start, window_end=window_end)
            return WVCPolicyResult("reused" if run.reused_existing else "completed", None,
                                   source_id, window_start, window_end, run)
