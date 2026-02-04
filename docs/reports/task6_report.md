# Task 6 Report: Pre-broadcast and reuse constants

## Goal
Implement IMPROVEMENTS_C.md task 6 only: pre-broadcast hash and arithmetic constants into vector scratch registers once before the main loop, and deduplicate them to avoid repeated loads/broadcasts.

## Plan
1. Create a `scratch_const()` helper to deduplicate scalar constant loads via `const_map`.
2. Create a `vec_const_map` / `alloc_vec_const()` helper to deduplicate vector constant broadcasts via `vbroadcast`.
3. Pre-allocate all constants (0, 1, 2, and all hash stage constants) before the main loop.
4. Reference pre-broadcast vector constants from `vec_const_map` inside `build_hash_vec()` and the inner loop.
5. Run the submission test suite to validate correctness and record performance.

## Changes Made
- Added `scratch_const()` method (line ~317) that deduplicates scalar constants via `self.const_map`, allocating scratch and issuing a `load const` only on first use.
- Added `alloc_vec_const()` nested function (line ~402) with `vec_const_map` dict that deduplicates vector constants, issuing `vbroadcast` only on first use.
- Pre-allocated `vec_zero`, `vec_one`, `vec_two`, and all hash stage constants (`val1`, `val3` per stage) before the main loop (lines ~412-418).
- `build_hash_vec()` references `vec_const_map[val1]` and `vec_const_map[val3]` instead of loading/broadcasting constants each iteration.

Files modified:
- `perf_takehome.py`

## Tests Run
- `python tests/submission_tests.py`

## Test Results
- Correctness test: passed.
- Speed tests: failed 6 thresholds. All runs reported `CYCLES: 2636` (speedup ~56.04x), which is above the tighter limits (e.g., 2164/1790/1579/1548/1487/1363).

## Notes / Issues
- Task 6 was already implemented prior to this report. The code was verified to contain `scratch_const()`, `vec_const_map`, and `alloc_vec_const()` with proper deduplication and pre-loop broadcasting.
- Task 7 (running pointers) was also already implemented at this point, so the reported cycle count of 2636 reflects both task 6 and task 7 being active. See task7_report.md for details on that optimization.
- Performance thresholds are still not met because only incremental improvements (tasks 1-7) have been applied. Further optimizations from IMPROVEMENTS_C.md would be required to pass the stricter speed tests.

## Status
Task 6 implementation confirmed complete; correctness preserved; performance at 2636 cycles (56.04x speedup over baseline).
