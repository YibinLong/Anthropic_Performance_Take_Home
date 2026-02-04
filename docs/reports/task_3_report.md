# Task 3 Report - Software Pipelining / Multi-Group Interleaving

## Summary
Implemented multi-group interleaving for the vectorized inner loop in `perf_takehome.py` to enable software pipelining across independent vector groups. The goal was to let the VLIW scheduler overlap load/gather/hash/store work from multiple groups in-flight.

## What Changed
- **File:** `perf_takehome.py`
- **Function:** `KernelBuilder.build_kernel`
- **Core change:** Introduced `interleave_groups = 8` and allocated **independent register sets per group** (vector regs + scalar address regs).
- **Loop restructuring:** The vector loop now processes chunks of `VLEN * interleave_groups` and emits per-group ops via a helper (`emit_vector_group_ops`). This keeps register dependencies isolated per group so the scheduler can interleave across groups.

## Rationale
The previous single-group vector loop reused the same scratch registers each iteration, which forced the scheduler to serialize work. By duplicating registers across groups and unrolling the loop in chunks, we create multiple independent dependency chains. This is the software pipelining / multi-group interleaving described in `C_improvements.md` task 3.

## Tests Run
Command (per `docs/running-tests.md`):
```
python tests/submission_tests.py 2>&1
```

## Test Results
- **Correctness:** Passed (kernel correctness test succeeded).
- **Performance:** Some speed thresholds still failed (expected without additional improvements).
- **Observed cycles:** `2660` for `forest_height=10, rounds=16, batch_size=256`.
- **Speedup over baseline:** `~55.54x` (reported by the harness).

Failures were limited to stricter speed targets (`test_opus4_many_hours` and tighter). No functional regressions were observed.

## Notes
- I briefly tested `interleave_groups = 4`, `8`, and `16`. `8` reduced cycles from ~3425 (4 groups) to ~2660. `16` did not improve further, so the final setting is `8`.
- Further speedups will likely require other tasks (e.g., removing flow `vselect` bottlenecks or hash-stage packing), but those were intentionally left untouched per the scope of Task 3.
