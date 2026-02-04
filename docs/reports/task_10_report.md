# Task 10 Report: multiply_add for applicable hash stages

## Goal
Implement C_improvements.md task 10 by using VALU `multiply_add` in the vector hash stages where the pattern is `(a OP1 const1) + (a << shift)`.

## Plan
1. Update `KernelBuilder.build_hash_vec()` to emit `multiply_add` for eligible stages (op2 `+` and op3 `<<`).
2. Add vector constants for the shift multipliers used by `multiply_add`.
3. Run `python tests/submission_tests.py` and record results.
4. Check off task 10 in `C_improvements.md`.

## Changes Made
- **Vector hash stages:** `build_hash_vec()` now emits:
  - `tmp1 = op1(a, const1)`
  - `a = multiply_add(a, mul_const, tmp1)`
  for stages where `op2 == "+"` and `op3 == "<<"` (stages 0, 2, 4 in `HASH_STAGES`).
- **Multiplier constants:** Precompute vector multipliers as `vec_one << shift_const` once before the loop and cache them in `vec_const_map` keyed by `1 << shift`.
- **Checklist:** Task 10 checked off in `docs/improvements/C_improvements.md`.

Files updated:
- `perf_takehome.py`
- `docs/improvements/C_improvements.md`

## Tests Run
- `python tests/submission_tests.py`

## Test Results
- Correctness test: **passed**.
- Speed tests: **3 passed, 6 failed**. All runs reported `CYCLES: 2637`.

| Test | Threshold | Result |
|------|-----------|--------|
| test_kernel_speedup | < 147734 | PASSED |
| test_kernel_updated_starting_point | < 18532 | PASSED |
| test_opus4_many_hours | < 2164 | FAILED (2637) |
| test_opus45_casual | < 1790 | FAILED (2637) |
| test_opus45_2hr | < 1579 | FAILED (2637) |
| test_sonnet45_many_hours | < 1548 | FAILED (2637) |
| test_opus45_11hr | < 1487 | FAILED (2637) |
| test_opus45_improved_harness | < 1363 | FAILED (2637) |

## Notes / Issues
- The cycle count is slightly higher than the previous baseline in task 9 (2636). The extra pre-loop multiplier setup likely offsets the per-stage slot savings in this configuration.
- No correctness regressions observed; the only failures are the expected speed thresholds that were already unmet before task 10.

## Status
Task 10 complete; correctness preserved; performance measured at 2637 cycles (56.02x speedup over baseline of 147,734).
