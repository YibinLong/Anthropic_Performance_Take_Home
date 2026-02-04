# Task 7 Report: Running pointers for input arrays

## Goal
Implement IMPROVEMENTS_C.md task 7 only: use running pointers for input indices/values to avoid per-iteration address adds, while keeping correctness with the existing VLIW scheduler.

## Plan
1. Locate the vectorized input load/store address computation in `perf_takehome.py`.
2. Replace per-iteration address adds with per-group running pointers, using flow `add_imm` updates.
3. Run submission tests and document correctness/performance.

## Changes Made
- Added per-group running pointers (`idx_ptr_g*`, `val_ptr_g*`) and “next” pointers (`*_next_g*`) to update addresses via `flow add_imm` without read-modify-write hazards.
- Reordered pointer updates to compute `next` before `vstore`, then move `next` into the current pointer after stores to preserve WAR ordering with the scheduler.
- Updated tail path (if any) to use the same pointer update pattern with `*_next` scratch.

Files modified:
- `perf_takehome.py`

## Task 6 Check
Task 6 (“pre-broadcast and reuse constants”) is already implemented and working via `vec_const_map` and `scratch_const()` in `build_kernel()`. No changes were required.

## Tests Run
- `python tests/submission_tests.py`

## Test Results
- Correctness test: passed.
- Speed tests: failed 6 thresholds. All runs reported `CYCLES: 2636` (speedup ~56.04x), which is above the tighter limits (e.g., 2164/1790/1579/1548/1487/1363).

## Notes / Issues
- Initial running-pointer implementation exposed a scheduler WAR hazard: read-modify-write `add_imm` on the same pointer register can be scheduled before the prior `vstore`, causing out-of-range loads. The fix uses `*_next` pointer registers and moves after stores to preserve ordering.
- Performance thresholds are still not met because only task 7 was implemented, as requested.

## Status
Task 7 implementation complete; correctness preserved; performance remains above the strictest speed thresholds.
