from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from perf_takehome import analyze_schedule as analyze_schedule_core
from perf_takehome import format_schedule_report

from .recommend import generate_candidates
from .schemas import (
    CandidateAction,
    CriticalPathNode,
    EnginePressure,
    PhaseBreakdown,
    RunDiagnostics,
)


def _to_run_diagnostics(report: dict[str, Any]) -> RunDiagnostics:
    engine_pressure = {
        engine: EnginePressure(
            engine=engine,
            avg=data["avg"],
            limit=data["limit"],
            util_pct=data["util_pct"],
            idle_slots=data.get("idle_slots", 0),
            saturation_cycles=data.get("saturation_cycles", 0),
            active_cycles=data.get("active_cycles", 0),
        )
        for engine, data in report["engine_pressure"].items()
    }
    phases = [
        PhaseBreakdown(
            phase=phase["phase"],
            cycles=phase["cycles"],
            engine_utilization=phase["engine_utilization"],
        )
        for phase in report.get("phases", [])
    ]
    critical_nodes = [
        CriticalPathNode(
            phase=node["phase"],
            op_id=node["op_id"],
            engine=node["engine"],
            slot_count=node["slot_count"],
            crit_path=node["crit_path"],
            cycle=node["cycle"],
        )
        for node in report.get("critical_path_top", [])
    ]
    candidates = [
        CandidateAction(
            action_id=c["action_id"],
            title=c["title"],
            hypothesis=c["hypothesis"],
            target_paths=c["target_paths"],
            expected_engine_impact=c["expected_engine_impact"],
            confidence=c["confidence"],
            risk_flags=c.get("risk_flags", []),
            suggested_parameters=c.get("suggested_parameters", {}),
        )
        for c in report.get("candidates", [])
    ]
    return RunDiagnostics(
        created_at_utc=report["created_at_utc"],
        cycle_count=report["cycle_count"],
        engine_pressure=engine_pressure,
        bottlenecks=report.get("bottlenecks", []),
        phases=phases,
        critical_path_top=critical_nodes,
        candidates=candidates,
        metadata=report.get("metadata", {}),
    )


def analyze_schedule_artifacts(
    instrs: list[dict[str, list[tuple]]],
    schedule_profile: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    include_debug: bool = False,
    include_candidates: bool = True,
) -> RunDiagnostics:
    metadata = dict(metadata or {})
    if schedule_profile is not None:
        metadata["schedule_profile"] = schedule_profile
    report = analyze_schedule_core(instrs, metadata=metadata, include_debug=include_debug)

    if include_candidates:
        report["candidates"] = generate_candidates(report)

    return _to_run_diagnostics(report)


def render_run_markdown(run_diag: RunDiagnostics) -> str:
    report = {
        "created_at_utc": run_diag.created_at_utc,
        "cycle_count": run_diag.cycle_count,
        "engine_pressure": {
            engine: {
                "avg": data.avg,
                "limit": data.limit,
                "util_pct": data.util_pct,
                "idle_slots": data.idle_slots,
                "saturation_cycles": data.saturation_cycles,
                "active_cycles": data.active_cycles,
            }
            for engine, data in run_diag.engine_pressure.items()
        },
        "bottlenecks": run_diag.bottlenecks,
        "critical_path_top": [
            {
                "phase": node.phase,
                "op_id": node.op_id,
                "engine": node.engine,
                "slot_count": node.slot_count,
                "crit_path": node.crit_path,
                "cycle": node.cycle,
            }
            for node in run_diag.critical_path_top
        ],
        "phases": [
            {
                "phase": phase.phase,
                "cycles": phase.cycles,
                "engine_utilization": phase.engine_utilization,
            }
            for phase in run_diag.phases
        ],
    }

    md = [format_schedule_report(report).rstrip(), "", "## Candidate Actions"]
    if not run_diag.candidates:
        md.append("- No candidates generated.")
    else:
        for c in run_diag.candidates:
            md.append(
                f"- `{c.action_id}` {c.title}: {c.hypothesis} "
                f"(confidence {c.confidence:.2f}, impact: {', '.join(c.expected_engine_impact)})"
            )
    md.append("")
    return "\n".join(md)


def write_run_artifacts(run_diag: RunDiagnostics, out_dir: str | Path) -> tuple[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "latest_run.json"
    md_path = out / "latest_run.md"
    json_path.write_text(json.dumps(run_diag.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(render_run_markdown(run_diag), encoding="utf-8")
    return str(json_path), str(md_path)
