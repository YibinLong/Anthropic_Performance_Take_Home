# Task 16 Report: Keep Full Batch in Scratch Across Rounds

Date: 2026-02-04

## Goal
Implement IMPROVEMENTS_C task 16: load the full batch of indices/values into scratch once, operate on scratch across all rounds, and store back once at the end.

## What Changed
- `perf_takehome.py`
  - Added `idx_arr` and `val_arr` scratch arrays sized to `batch_size`.
  - Added a **prelude** that vloads indices/values from memory into scratch once.
  - Updated the vectorized round body to operate directly on scratch arrays and removed per-round vload/vstore to memory.
  - Added a **final epilogue** that stores scratch arrays back to memory once after all rounds.
  - Switched vector idx update to `multiply_add(idx, vec_two, branch)` so the scheduler cannot hoist the shift ahead of the gather (fixing a correctness issue with VLIW reordering when idx lives in scratch across rounds).

## Tests Run
Command:
```
python tests/submission_tests.py
```

Result:
- Correctness test passed.
- Speed tests failed (6/8) with cycles reported at **2177**.

## Issues Encountered & Fixes
1. **Out-of-range memory access after moving idx/val to scratch**
   - Cause: VLIW scheduling hoisted `idx <<= 1` ahead of the gather, so gather used already-shifted indices (out of range).
   - Fix: replaced the separate shift+add with a single `multiply_add(idx, vec_two, branch)` op that depends on the hashed value, preventing the hoist.

## Final Status
- Task 16 implemented and checked off.
- Kernel correctness intact.
- Performance improved to 2177 cycles but remains above the 2164 threshold.

## Files Touched
- `perf_takehome.py`
- `docs/improvements/IMPROVEMENTS_C.md`
- `docs/reports/task16_report.md`
