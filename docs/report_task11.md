# Task 11 Report: Scratch Reuse / Liveness-Driven Packing

## Scope
- Implement improvement #11 from `docs/improvements/IMPROVEMENTS_C.md`.
- Reuse dead vector scratch registers to reduce per-group scratch usage.
- No behavior changes; interleaving depth remains at 8.

## Changes Made
- `perf_takehome.py`: Removed per-group `vec_tmp1`/`vec_tmp2` allocations and aliased:
  - `vec_tmp1` -> `vec_addr`
  - `vec_tmp2` -> `vec_node_val`
  This reuses scratch after address calculation and node-value XOR are complete.
- `docs/improvements/IMPROVEMENTS_C.md`: Checked off task 11 with a short status note.

## Rationale / Safety Notes
- `vec_addr` is only needed for `load_offset` address reads; after the gather it is dead.
- `vec_node_val` is only needed through `val ^= node_val`; after XOR it is dead.
- Writing new temporaries into these slots is safe because WAR hazards are allowed (reads observe old values in the same cycle; writes commit at cycle end).

## Tests Run
- `python tests/submission_tests.py`

### Results
- Correctness test passed.
- Speed tests failed due to current cycle count:
  - `CYCLES: 2637`
  - Failed thresholds: 2164, 1790, 1579, 1548, 1487, 1363

## Issues Encountered
- No functional regressions observed.
- Performance thresholds remain unmet; resolving them requires additional optimizations beyond task 11.

## Files Touched
- `perf_takehome.py`
- `docs/improvements/IMPROVEMENTS_C.md`
- `docs/report_task11.md`
