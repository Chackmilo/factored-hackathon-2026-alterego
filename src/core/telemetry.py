import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class ExecutionMetrics:
    total_latency_ms: float = 0.0
    stage_latencies_ms: Dict[str, float] = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    pii_entities_redacted: int = 0
    rules_triggered: List[str] = field(default_factory=list)

class TelemetryTracker:
    def __init__(self):
        self._start_time: float = time.perf_counter()
        self.metrics = ExecutionMetrics()
        self._stage_starts: Dict[str, float] = {}

    def start_stage(self, stage_name: str) -> None:
        self._stage_starts[stage_name] = time.perf_counter()

    def end_stage(self, stage_name: str) -> float:
        if stage_name in self._stage_starts:
            duration_ms = (time.perf_counter() - self._stage_starts.pop(stage_name)) * 1000.0
            self.metrics.stage_latencies_ms[stage_name] = round(duration_ms, 2)
            return duration_ms
        return 0.0

    def record_tokens(self, prompt_tokens: int, completion_tokens: int, cost_per_1k_tokens: float = 0.0015) -> None:
        self.metrics.prompt_tokens += prompt_tokens
        self.metrics.completion_tokens += completion_tokens
        total_tokens = prompt_tokens + completion_tokens
        self.metrics.estimated_cost_usd += (total_tokens / 1000.0) * cost_per_1k_tokens

    def record_pii_redacted(self, count: int) -> None:
        self.metrics.pii_entities_redacted += count

    def record_rule(self, rule_name: str) -> None:
        self.metrics.rules_triggered.append(rule_name)

    def finalize(self) -> ExecutionMetrics:
        self.metrics.total_latency_ms = round((time.perf_counter() - self._start_time) * 1000.0, 2)
        return self.metrics
