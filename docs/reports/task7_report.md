# Task 7 Report: Running pointers for input arrays

## Goal
Implement IMPROVEMENTS_C.md task 7 only: keep running pointers for input indices/values and cut per-iteration address arithmetic, while preserving correctness under the VLIW scheduler.

## Plan
1. Inspect the vectorized inner-loop address handling in `perf_takehome.py` and map where input pointers are advanced.
2. Update pointer progression so values pointers stay aligned with indices without extra flow slots.
3. Run submission tests and record correctness/perf results.

## Changes Made
- Kept per-group running index pointers (`idx_ptr_g*`) advanced with `flow add_imm`.
- Removed per-iteration `val_ptr_next` flow updates; instead, derive `val_ptr` from `idx_ptr_next + batch_size` in a single ALU bundle, keeping pointers in sync while reducing flow-slot pressure.
- Applied the same pattern to the scalar tail path: `tail_val_ptr` now updates from `tail_idx_ptr_next + batch_size`.

Files modified:
- `perf_takehome.py`

## Tests Run
- `python tests/submission_tests.py`

## Test Results
- Correctness test: **passed**.
- Speed tests: **failed 6 thresholds**. All runs reported `CYCLES: 2636` (speedup ~56.04x), which is above the tighter limits (2164/1790/1579/1548/1487/1363).

## Notes / Issues
- The updated pointer scheme preserves correctness and avoids the earlier desynchronization risks of in-place `idx_ptr`/`val_ptr` updates across groups.
- Performance targets beyond task 7 remain unmet, which is expected when only this optimization is applied.

## Status
Task 7 implementation complete and correct. Performance remains above the strictest speed thresholds, consistent with only applying task 7.
