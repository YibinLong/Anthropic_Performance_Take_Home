# Task 13 Report: Eliminate Unused Header Loads

Date: 2026-02-04

## Goal
Implement IMPROVEMENTS_C.md task 13: remove unused header loads (rounds, batch_size, forest_height) from `KernelBuilder.build_kernel`, keeping only the headers actually used by the optimized kernel.

## What Changed
- `perf_takehome.py`
  - Replaced the header init list with explicit `(name, header_index)` pairs so correct header indices are still loaded after removing unused headers.
  - Removed allocations/loads for `rounds`, `batch_size`, and `forest_height`.
  - Added a build-time `batch_size_const` and replaced pointer math that previously used `self.scratch["batch_size"]`.
- `docs/improvements/IMPROVEMENTS_C.md`
  - Checked off task 13.

## Why the Header Index Fix Was Needed
Removing entries from the header load list shifted indices; the header layout is fixed (mem[0..6]). I updated the load loop to use explicit indices to avoid loading the wrong values (this initially caused an out-of-range memory access during gather).

## Tests Run
Command:
```
python tests/submission_tests.py
```

Result:
- Correctness tests passed.
- Speed tests failed (6/8) with cycles reported at **2632**.

Full test output (summary):
- Pass: `test_kernel_correctness`, `test_kernel_speedup`, `test_kernel_updated_starting_point`
- Fail: `test_opus4_many_hours`, `test_opus45_casual`, `test_opus45_2hr`, `test_sonnet45_many_hours`, `test_opus45_11hr`, `test_opus45_improved_harness`

## Issues Encountered & Fixes
1. **Out-of-range memory access** after removing headers.
   - Cause: header indices were implicitly derived from list order; after removing entries, `n_nodes` and pointers were loaded from the wrong header slots.
   - Fix: load headers using explicit indices `(n_nodes=1, forest_values_p=4, inp_indices_p=5, inp_values_p=6)`.

## Final Status
- Task 13 implemented and checked off.
- Kernel correctness intact.
- Performance tests still above some speed thresholds (cycles 2632); no further optimizations applied since the request was limited to task 13.

## Files Touched
- `perf_takehome.py`
- `docs/improvements/IMPROVEMENTS_C.md`
- `docs/reports/task13_report.md`
