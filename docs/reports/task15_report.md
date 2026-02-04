# Task 15 Report: IR Optimizer Pass (DCE)

Date: 2026-02-04

## Goal
Implement IMPROVEMENTS_C task 15: add an IR optimizer pass (dead-code elimination / const dedup) before scheduling.

## What Changed
- `perf_takehome.py`
  - Added `_slot_side_effect()` and `_optimize_slots()` to perform a backward DCE pass over slot lists.
  - Integrated the optimizer into `KernelBuilder.build()` so each VLIW segment is optimized before scheduling.
- `docs/improvements/IMPROVEMENTS_C.md`
  - Checked off task 15.

## Notes on Scope
- The optimizer removes unused ALU/VALU/LOAD work by tracking live scratch writes.
- Flow, store, and debug ops are treated as side effects and are always kept.
- Constant dedup is largely already handled via `scratch_const()` and `vec_const_map`; this pass focuses on DCE safety.

## Tests Run
Command:
```
python tests/submission_tests.py
```

Result:
- Correctness test passed.
- Speed tests failed (6/8) with cycles reported at **2632** (no change).

## Issues Encountered & Fixes
- None. DCE did not alter the schedule materially for the current kernel shape.

## Final Status
- Task 15 implemented and checked off.
- Kernel correctness intact.
- Performance thresholds above 2164 remain unmet (cycles 2632).

## Files Touched
- `perf_takehome.py`
- `docs/improvements/IMPROVEMENTS_C.md`
- `docs/reports/task15_report.md`
