# Task 14 Report: Small Arithmetic Simplifications

Date: 2026-02-04

## Goal
Implement IMPROVEMENTS_C task 14: small arithmetic simplifications in the hot path (e.g., replace `* 2` with `<< 1`).

## What Changed
- `perf_takehome.py`
  - Replaced vector `idx * 2` with `idx << 1` using `vec_one`.
  - Replaced scalar tail `idx * 2` with `idx << 1` using `one_const`.
- `docs/improvements/C_improvements.md`
  - Checked off task 14.

## Tests Run
Command:
```
python tests/submission_tests.py
```

Result:
- Correctness test passed.
- Speed tests failed (6/8) with cycles reported at **2632**.

## Issues Encountered & Fixes
- None. This task is a micro-optimization; cycle count remained unchanged at 2632.

## Final Status
- Task 14 implemented and checked off.
- Kernel correctness intact.
- Performance thresholds above 2164 remain unmet (cycles 2632).

## Files Touched
- `perf_takehome.py`
- `docs/improvements/C_improvements.md`
- `docs/reports/task14_report.md`
