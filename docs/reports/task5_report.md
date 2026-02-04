# Task 5 Report: Remove flow selects with arithmetic (parity + wrap)

## Goal
Implement IMPROVEMENTS_C.md task 5 only: replace flow `select`/`vselect` in the parity and wrap steps with pure ALU/VALU arithmetic.

## Plan
1. Locate parity + wrap logic in `perf_takehome.py` for both vector and scalar tail paths.
2. Replace `select`/`vselect` with arithmetic equivalents:
   - Parity: `branch = (val & 1) + 1`
   - Wrap: `idx = idx * (idx < n_nodes)`
3. Run the submission test suite to validate correctness and record performance impact.

## Changes Made
- Vector path (SIMD): removed `valu %`, `valu ==`, and `flow vselect`; replaced with `valu &`, `valu +`, and `valu *` for wrap.
- Scalar tail path: removed `alu %`, `alu ==`, and `flow select`; replaced with `alu &`, `alu +`, and `alu *` for wrap.

Files modified:
- `perf_takehome.py`

## Tests Run
- `python tests/submission_tests.py`

## Test Results
- Correctness test: passed.
- Speed tests: failed (6 failures). All runs reported `CYCLES: 2660` with speedup ~55.54x, which is above the tighter thresholds (e.g., 2164/1790/1579/1548/1487/1363).

## Notes / Issues
- Performance thresholds are not met because only task 5 was implemented, as requested. Further improvements from IMPROVEMENTS_C.md would be required to pass the stricter speed tests.

## Status
Task 5 implementation complete; no functional correctness regressions detected in the submission test suite.
