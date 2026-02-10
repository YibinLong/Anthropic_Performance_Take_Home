from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from perf_takehome import do_kernel_test
from tools.opt_debug.analyze_schedule import analyze_schedule_artifacts


def run() -> None:
    parser = argparse.ArgumentParser(description="Standalone sanity checks for opt_debug tooling.")
    parser.add_argument(
        "--out-dir",
        type=str,
        default="",
        help="Optional output directory to retain generated diagnostics.",
    )
    args = parser.parse_args()

    # Check 1: schedule analyzer returns expected structure on a tiny synthetic program.
    instrs = [
        {"valu": [("+", 1, 2, 3)]},
        {"load": [("const", 4, 123)], "flow": [("halt",)]},
    ]
    run_diag = analyze_schedule_artifacts(instrs, include_candidates=True)
    assert run_diag.cycle_count == 2
    assert "valu" in run_diag.engine_pressure
    assert len(run_diag.candidates) >= 1

    # Check 2: kernel run can emit diagnostics artifacts and preserve expected cycles.
    if args.out_dir:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        cleanup = False
    else:
        out_dir = Path(tempfile.mkdtemp(prefix="opt_debug_selfcheck_"))
        cleanup = True

    cycles = do_kernel_test(
        10,
        16,
        256,
        diagnostics_out=str(out_dir),
        kernel_kwargs={
            "interleave_groups": 25,
            "interleave_groups_early": 26,
        },
    )
    assert cycles == 1478, f"unexpected cycle count: {cycles}"

    json_path = out_dir / "latest_run.json"
    md_path = out_dir / "latest_run.md"
    assert json_path.exists(), "latest_run.json was not created"
    assert md_path.exists(), "latest_run.md was not created"

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["cycle_count"] == 1478
    assert "engine_pressure" in payload
    assert "candidates" in payload

    summary = {
        "status": "ok",
        "cycles": cycles,
        "latest_run_json": str(json_path),
        "latest_run_md": str(md_path),
        "temp_output": cleanup,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    run()
