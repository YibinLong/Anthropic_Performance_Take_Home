from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EnginePressure:
    engine: str
    avg: float
    limit: int
    util_pct: float
    idle_slots: int
    saturation_cycles: int
    active_cycles: int


@dataclass
class PhaseBreakdown:
    phase: str
    cycles: int
    engine_utilization: dict[str, dict[str, float]]


@dataclass
class CriticalPathNode:
    phase: str
    op_id: int
    engine: str
    slot_count: int
    crit_path: int
    cycle: int


@dataclass
class CandidateAction:
    action_id: str
    title: str
    hypothesis: str
    target_paths: list[str]
    expected_engine_impact: list[str]
    confidence: float
    risk_flags: list[str] = field(default_factory=list)
    suggested_parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunDiagnostics:
    created_at_utc: str
    cycle_count: int
    engine_pressure: dict[str, EnginePressure]
    bottlenecks: list[dict[str, Any]]
    phases: list[PhaseBreakdown]
    critical_path_top: list[CriticalPathNode]
    candidates: list[CandidateAction] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExperimentResult:
    trial_id: int
    params: dict[str, Any]
    cycles: int
    passed_correctness: bool
    delta_cycles: int
    diagnostics_path: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
