from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import shutil
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from perf_takehome import BASELINE, KernelBuilder
from tests.frozen_problem import (  # type: ignore
    Input,
    Machine,
    N_CORES,
    Tree,
    build_mem_image,
    reference_kernel2,
)
from tools.opt_debug.analyze_schedule import (
    analyze_schedule_artifacts,
    render_run_markdown,
)
from tools.opt_debug.analyze_trace import analyze_trace
from tools.opt_debug.schemas import ExperimentResult, RunDiagnostics


def _evaluate_once(
    params: dict[str, Any],
    *,
    seed: int,
    forest_height: int,
    rounds: int,
    batch_size: int,
    out_dir: Path,
    trial_id: int,
    trace: bool = False,
) -> tuple[ExperimentResult, RunDiagnostics | None]:
    random.seed(seed)
    forest = Tree.generate(forest_height)
    inp = Input.generate(forest, batch_size, rounds)
    mem = build_mem_image(forest, inp)

    trial_dir = out_dir / "trials" / f"trial_{trial_id:04d}"
    trial_dir.mkdir(parents=True, exist_ok=True)

    kb = KernelBuilder(
        emit_debug=False,
        trace_phase_tags=True,
        scheduler_profile=True,
        interleave_groups=params["interleave_groups"],
        interleave_groups_early=params["interleave_groups_early"],
        depth2_select_mode=params["depth2_select_mode"],
        idx_branch_mode=params["idx_branch_mode"],
        scheduler_crit_weight=params["scheduler_crit_weight"],
        scheduler_engine_bias=params["scheduler_engine_bias"],
    )
    kb.build_kernel(forest.height, len(forest.values), len(inp.indices), rounds)

    machine = Machine(
        mem,
        kb.instrs,
        kb.debug_info(),
        n_cores=N_CORES,
        trace=trace,
    )
    machine.enable_pause = False
    machine.enable_debug = False
    machine.run()

    for ref_mem in reference_kernel2(mem):
        pass

    inp_values_p = ref_mem[6]
    passed = (
        machine.mem[inp_values_p : inp_values_p + len(inp.values)]
        == ref_mem[inp_values_p : inp_values_p + len(inp.values)]
    )

    diagnostics = analyze_schedule_artifacts(
        kb.instrs,
        schedule_profile=kb.schedule_profile(),
        metadata={
            "seed": seed,
            "forest_height": forest_height,
            "rounds": rounds,
            "batch_size": batch_size,
            "kernel_config": params,
            "trial_id": trial_id,
            "cycles": machine.cycle,
            "correct": passed,
        },
        include_candidates=True,
    )

    diag_json = trial_dir / "diagnostics.json"
    diag_md = trial_dir / "diagnostics.md"
    diag_json.write_text(json.dumps(diagnostics.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    diag_md.write_text(render_run_markdown(diagnostics), encoding="utf-8")

    trace_summary_path: str | None = None
    if trace:
        # Ensure trace.json is finalized before parsing.
        if getattr(machine, "trace", None) is not None:
            machine.trace.write("]")
            machine.trace.close()
            machine.trace = None
        trace_report = analyze_trace(REPO_ROOT / "trace.json")
        trace_json = trial_dir / "trace_report.json"
        trace_json.write_text(json.dumps(trace_report, indent=2, sort_keys=True), encoding="utf-8")
        trace_summary_path = str(trace_json)

    result = ExperimentResult(
        trial_id=trial_id,
        params=params,
        cycles=machine.cycle,
        passed_correctness=passed,
        delta_cycles=machine.cycle - 1478,
        diagnostics_path=str(diag_json),
        notes=(f"trace={trace_summary_path}" if trace_summary_path else None),
    )
    return result, diagnostics


def _sample_params(rng: random.Random) -> dict[str, Any]:
    crit_weights = [256, 512, 768, 1024, 1536, 2048, 3072, 4096]
    return {
        "interleave_groups": rng.randint(20, 30),
        "interleave_groups_early": rng.randint(20, 30),
        "depth2_select_mode": rng.choice(["flow_vselect", "alu_blend"]),
        "idx_branch_mode": rng.choice(["flow_vselect", "alu_branch"]),
        "scheduler_crit_weight": rng.choice(crit_weights),
        "scheduler_engine_bias": {
            "load": rng.choice([-128, -64, 0, 64, 128]),
            "flow": rng.choice([-128, -64, 0, 64, 128]),
            "valu": rng.choice([-64, 0, 64]),
        },
    }


def _run_optuna(
    n_trials: int,
    seed: int,
    forest_height: int,
    rounds: int,
    batch_size: int,
    out_dir: Path,
) -> tuple[list[ExperimentResult], dict[int, RunDiagnostics | None]]:
    import optuna

    results: list[ExperimentResult] = []
    diagnostics_by_trial: dict[int, RunDiagnostics | None] = {}

    sampler = optuna.samplers.TPESampler(seed=seed)
    pruner = optuna.pruners.MedianPruner(n_warmup_steps=5)
    study = optuna.create_study(direction="minimize", sampler=sampler, pruner=pruner)

    def objective(trial: "optuna.Trial") -> float:
        params = {
            "interleave_groups": trial.suggest_int("interleave_groups", 20, 30),
            "interleave_groups_early": trial.suggest_int("interleave_groups_early", 20, 30),
            "depth2_select_mode": trial.suggest_categorical(
                "depth2_select_mode", ["flow_vselect", "alu_blend"]
            ),
            "idx_branch_mode": trial.suggest_categorical(
                "idx_branch_mode", ["flow_vselect", "alu_branch"]
            ),
            "scheduler_crit_weight": trial.suggest_categorical(
                "scheduler_crit_weight", [256, 512, 768, 1024, 1536, 2048, 3072, 4096]
            ),
            "scheduler_engine_bias": {
                "load": trial.suggest_int("sched_bias_load", -128, 128, step=64),
                "flow": trial.suggest_int("sched_bias_flow", -128, 128, step=64),
                "valu": trial.suggest_int("sched_bias_valu", -64, 64, step=64),
            },
        }
        result, diag = _evaluate_once(
            params,
            seed=seed + trial.number,
            forest_height=forest_height,
            rounds=rounds,
            batch_size=batch_size,
            out_dir=out_dir,
            trial_id=trial.number,
        )
        results.append(result)
        diagnostics_by_trial[result.trial_id] = diag

        trial.set_user_attr("cycles", result.cycles)
        trial.set_user_attr("passed_correctness", result.passed_correctness)
        trial.set_user_attr("diagnostics_path", result.diagnostics_path)

        if not result.passed_correctness:
            return float(BASELINE * 2)
        return float(result.cycles)

    study.optimize(objective, n_trials=n_trials)
    return results, diagnostics_by_trial


def _run_random(
    n_trials: int,
    seed: int,
    forest_height: int,
    rounds: int,
    batch_size: int,
    out_dir: Path,
) -> tuple[list[ExperimentResult], dict[int, RunDiagnostics | None]]:
    rng = random.Random(seed)
    results: list[ExperimentResult] = []
    diagnostics_by_trial: dict[int, RunDiagnostics | None] = {}
    for i in range(n_trials):
        params = _sample_params(rng)
        result, diag = _evaluate_once(
            params,
            seed=seed + i,
            forest_height=forest_height,
            rounds=rounds,
            batch_size=batch_size,
            out_dir=out_dir,
            trial_id=i,
        )
        results.append(result)
        diagnostics_by_trial[result.trial_id] = diag
    return results, diagnostics_by_trial


def _render_leaderboard_md(results: list[ExperimentResult]) -> str:
    lines = [
        "# Auto-Optimizer Leaderboard",
        "",
        f"Baseline threshold reference: `{BASELINE}` cycles",
        "",
        "| Rank | Trial | Cycles | Correct | Delta vs 1478 |",
        "|---|---:|---:|---:|---:|",
    ]
    sorted_results = sorted(results, key=lambda r: (not r.passed_correctness, r.cycles))
    for idx, res in enumerate(sorted_results[:20], start=1):
        lines.append(
            f"| {idx} | {res.trial_id} | {res.cycles} | {str(res.passed_correctness)} | {res.delta_cycles:+d} |"
        )
    lines.append("")
    return "\n".join(lines)


def run() -> None:
    parser = argparse.ArgumentParser(description="Automated optimization search for perf_takehome kernel.")
    parser.add_argument("--trials", type=int, default=24)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--forest-height", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=16)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument(
        "--out-dir",
        type=str,
        default=str(REPO_ROOT / "docs" / "reports" / "optimizations" / "debug"),
    )
    parser.add_argument(
        "--backend",
        type=str,
        default="auto",
        choices=["auto", "optuna", "random"],
        help="Search backend. 'auto' uses optuna when installed, else random.",
    )
    parser.add_argument(
        "--trace-best",
        action="store_true",
        help="Generate and analyze trace.json for the best discovered config.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    backend = args.backend
    if backend == "auto":
        try:
            import optuna  # noqa: F401

            backend = "optuna"
        except Exception:
            backend = "random"

    if backend == "optuna":
        results, diagnostics_by_trial = _run_optuna(
            n_trials=args.trials,
            seed=args.seed,
            forest_height=args.forest_height,
            rounds=args.rounds,
            batch_size=args.batch_size,
            out_dir=out_dir,
        )
    else:
        results, diagnostics_by_trial = _run_random(
            n_trials=args.trials,
            seed=args.seed,
            forest_height=args.forest_height,
            rounds=args.rounds,
            batch_size=args.batch_size,
            out_dir=out_dir,
        )

    leaderboard_json = out_dir / "leaderboard.json"
    leaderboard_md = out_dir / "leaderboard.md"
    leaderboard_json.write_text(
        json.dumps([r.to_dict() for r in sorted(results, key=lambda x: (not x.passed_correctness, x.cycles))], indent=2),
        encoding="utf-8",
    )
    leaderboard_md.write_text(_render_leaderboard_md(results), encoding="utf-8")

    best = min(results, key=lambda r: (not r.passed_correctness, r.cycles))
    best_trial_dir = out_dir / "trials" / f"trial_{best.trial_id:04d}"
    best_diag_json = best_trial_dir / "diagnostics.json"
    best_diag_md = best_trial_dir / "diagnostics.md"
    shutil.copyfile(best_diag_json, out_dir / "latest_run.json")
    shutil.copyfile(best_diag_md, out_dir / "latest_run.md")

    if args.trace_best:
        best_params = best.params
        _evaluate_once(
            best_params,
            seed=args.seed + best.trial_id,
            forest_height=args.forest_height,
            rounds=args.rounds,
            batch_size=args.batch_size,
            out_dir=out_dir,
            trial_id=best.trial_id,
            trace=True,
        )

    summary = {
        "backend": backend,
        "trials": args.trials,
        "best_trial": best.to_dict(),
        "leaderboard_json": str(leaderboard_json),
        "leaderboard_md": str(leaderboard_md),
        "latest_run_json": str(out_dir / "latest_run.json"),
        "latest_run_md": str(out_dir / "latest_run.md"),
    }
    (out_dir / "run_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    run()
