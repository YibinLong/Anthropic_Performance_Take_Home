# Task 2 Implementation Report (SIMD Vectorization + Gather)

## Scope
- Implemented **only** IMPROVEMENTS_C task 2: SIMD vectorization of the inner loop with `vload`/`vstore`, `valu` arithmetic, and gather via `load_offset`.
- Did **not** implement other ranked improvements (scheduler, pipelining, flow-select elimination, etc.).

## Plan Followed
1. Map vector scratch layout and vectorized loop structure.
2. Implement vectorized inner loop with gather loads and vector hash.
3. Run submission tests and document outcomes.

## Code Changes
- Added a vectorized hash builder (`build_hash_vec`) using `valu` ops and `vcompare` for debug tracing.
- Rewrote the main loop in `KernelBuilder.build_kernel()` to:
  - Process `batch_size` in `VLEN`-sized chunks via `vload`/`vstore`.
  - Compute gather addresses as `forest_values_p + idx_vec` and load with `load_offset`.
  - Run hash and index update in SIMD using `valu` and `vselect`.
  - Keep a scalar tail loop for non-multiple-of-`VLEN` cases.
- Pre-broadcasted vector constants needed by the SIMD hash and branch logic.

## Tests Run
- `python tests/submission_tests.py`

## Results
- **Correctness:** Passed (no incorrect output values).
- **Performance:** `CYCLES: 14415` (Speedup over baseline ≈ 10.25x).
- **Speed test failures:**
  - `test_opus4_many_hours` (threshold 2164)
  - `test_opus45_casual` (threshold 1790)
  - `test_opus45_2hr` (threshold 1579)
  - `test_sonnet45_many_hours` (threshold 1548)
  - `test_opus45_11hr` (threshold 1487)
  - `test_opus45_improved_harness` (threshold 1363)

## Notes / Issues
- The SIMD vectorization alone is not sufficient to meet the more aggressive cycle thresholds. Achieving those would require additional improvements (e.g., VLIW scheduling, pipelining, flow-select elimination), which were explicitly **out of scope** for this task.

## Status
- Task 2 implemented and functionally correct.
- Performance targets beyond the “updated starting point” remain unmet due to scope restriction.
