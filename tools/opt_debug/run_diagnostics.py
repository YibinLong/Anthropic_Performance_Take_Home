from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from perf_takehome import KernelBuilder
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


def run() -> None:
    parser = argparse.ArgumentParser(description="Generate schedule diagnostics for one kernel config.")
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--forest-height", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=16)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--interleave-groups", type=int, default=25)
    parser.add_argument("--interleave-groups-early", type=int, default=26)
    parser.add_argument("--depth2-select-mode", choices=["flow_vselect", "alu_blend"], default="flow_vselect")
    parser.add_argument("--idx-branch-mode", choices=["flow_vselect", "alu_branch"], default="flow_vselect")
    parser.add_argument("--scheduler-crit-weight", type=int, default=1024)
    parser.add_argument("--sched-bias-load", type=int, default=0)
    parser.add_argument("--sched-bias-flow", type=int, default=0)
    parser.add_argument("--sched-bias-valu", type=int, default=0)
    parser.add_argument(
        "--out-dir",
        type=str,
        default=str(REPO_ROOT / "docs" / "reports" / "optimizations" / "debug"),
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    params = {
        "interleave_groups": args.interleave_groups,
        "interleave_groups_early": args.interleave_groups_early,
        "depth2_select_mode": args.depth2_select_mode,
        "idx_branch_mode": args.idx_branch_mode,
        "scheduler_crit_weight": args.scheduler_crit_weight,
        "scheduler_engine_bias": {
            "load": args.sched_bias_load,
            "flow": args.sched_bias_flow,
            "valu": args.sched_bias_valu,
        },
    }

    random.seed(args.seed)
    forest = Tree.generate(args.forest_height)
    inp = Input.generate(forest, args.batch_size, args.rounds)
    mem = build_mem_image(forest, inp)

    kb = KernelBuilder(emit_debug=False, scheduler_profile=True, trace_phase_tags=True, **params)
    kb.build_kernel(forest.height, len(forest.values), len(inp.indices), args.rounds)

    machine = Machine(mem, kb.instrs, kb.debug_info(), n_cores=N_CORES)
    machine.enable_pause = False
    machine.enable_debug = False
    machine.run()

    for ref_mem in reference_kernel2(mem):
        pass

    inp_values_p = ref_mem[6]
    correct = (
        machine.mem[inp_values_p : inp_values_p + len(inp.values)]
        == ref_mem[inp_values_p : inp_values_p + len(inp.values)]
    )

    run_diag = analyze_schedule_artifacts(
        kb.instrs,
        schedule_profile=kb.schedule_profile(),
        metadata={
            "seed": args.seed,
            "forest_height": args.forest_height,
            "rounds": args.rounds,
            "batch_size": args.batch_size,
            "kernel_config": params,
            "cycles": machine.cycle,
            "correct": correct,
        },
    )

    (out_dir / "latest_run.json").write_text(
        json.dumps(run_diag.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
    (out_dir / "latest_run.md").write_text(render_run_markdown(run_diag), encoding="utf-8")

    print(
        json.dumps(
            {
                "cycles": machine.cycle,
                "correct": correct,
                "latest_run_json": str(out_dir / "latest_run.json"),
                "latest_run_md": str(out_dir / "latest_run.md"),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    run()
