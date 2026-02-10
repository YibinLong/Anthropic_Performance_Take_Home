from __future__ import annotations

from typing import Any


def _mk(
    action_id: str,
    title: str,
    hypothesis: str,
    expected_engine_impact: list[str],
    confidence: float,
    target_paths: list[str] | None = None,
    risk_flags: list[str] | None = None,
    suggested_parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "title": title,
        "hypothesis": hypothesis,
        "target_paths": target_paths or ["perf_takehome.py"],
        "expected_engine_impact": expected_engine_impact,
        "confidence": confidence,
        "risk_flags": risk_flags or [],
        "suggested_parameters": suggested_parameters or {},
    }


def generate_candidates(report: dict[str, Any]) -> list[dict[str, Any]]:
    pressure = report.get("engine_pressure", {})
    candidates: list[dict[str, Any]] = []

    valu = pressure.get("valu", {})
    load = pressure.get("load", {})
    flow = pressure.get("flow", {})

    if valu.get("util_pct", 0) >= 90:
        candidates.append(
            _mk(
                "cand_valu_001",
                "Reduce VALU pressure in depth-specific path",
                "VALU is near saturation, so replacing arithmetic with flow where safe or reducing per-depth operations should lower cycle count.",
                ["valu"],
                0.78,
                target_paths=["perf_takehome.py"],
                risk_flags=["flow vselect scheduling hazards seen previously"],
                suggested_parameters={
                    "depth2_select_mode": ["flow_vselect", "alu_blend"],
                    "idx_branch_mode": ["flow_vselect", "alu_branch"],
                },
            )
        )

    if load.get("util_pct", 0) >= 85:
        candidates.append(
            _mk(
                "cand_load_001",
                "Lower gather cost for deeper rounds",
                "Load engine pressure indicates gather rounds still dominate; reducing gather frequency or clustering gather-heavy groups can free cycles.",
                ["load"],
                0.66,
                risk_flags=["depth-3+ transformations can break correctness if dependencies are weak"],
            )
        )

    if flow.get("util_pct", 0) >= 30:
        candidates.append(
            _mk(
                "cand_flow_001",
                "Tune flow/VALU tradeoff",
                "Flow usage is material and can bottleneck at one slot per cycle; test arithmetic alternatives when they do not increase VALU critical path too much.",
                ["flow", "valu"],
                0.62,
                suggested_parameters={
                    "idx_branch_mode": ["flow_vselect", "alu_branch"],
                },
            )
        )

    candidates.append(
        _mk(
            "cand_sched_001",
            "Retune scheduler priority bias",
            "Different critical-path and engine bias weights can improve slot fill without changing kernel semantics.",
            ["valu", "load", "flow"],
            0.71,
            target_paths=["perf_takehome.py", "tools/opt_debug/auto_optimize.py"],
            suggested_parameters={
                "scheduler_crit_weight": [256, 512, 1024, 2048],
                "scheduler_engine_bias": {
                    "load": [-128, -64, 0, 64, 128],
                    "flow": [-128, -64, 0, 64, 128],
                },
            },
        )
    )

    # History-derived guardrails from previous regressions in the repository reports.
    candidates.append(
        _mk(
            "cand_guardrails_001",
            "Preserve known safety guardrails",
            "Apply new experiments with explicit dependency anchoring and avoid previously regressive root-cache and weakly anchored vselect rewrites.",
            ["correctness"],
            0.95,
            target_paths=[
                "docs/reports/optimizations/00_optimization_landscape.md",
                "docs/reports/optimizations/8_optimization_summary.md",
            ],
            risk_flags=[
                "root scratch cache previously regressed",
                "depth-2 vselect rewrites can break due to register reuse",
            ],
        )
    )

    return candidates
