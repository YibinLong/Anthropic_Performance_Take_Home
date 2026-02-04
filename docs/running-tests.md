# Running Tests

## Quick Start

From the project root:

```bash
python tests/submission_tests.py
```

No additional test runner (pytest, etc.) is needed. The test file uses Python's built-in `unittest` and calls `unittest.main()` directly.

## What the Tests Do

There are **9 tests** across two test classes:

### CorrectnessTests (1 test)

- **`test_kernel_correctness`** — Runs the kernel with `forest_height=10`, `rounds=16`, `batch_size=256` for 8 random iterations. Compares output values against a reference implementation. This must always pass.

### SpeedTests (8 tests)

Each speed test runs the kernel and asserts that the cycle count is below a specific threshold. They represent progressively harder performance targets:

| Test Name | Max Cycles |
|---|---|
| `test_kernel_speedup` | 147,734 |
| `test_kernel_updated_starting_point` | 18,532 |
| `test_opus4_many_hours` | 2,164 |
| `test_opus45_casual` | 1,790 |
| `test_opus45_2hr` | 1,579 |
| `test_sonnet45_many_hours` | 1,548 |
| `test_opus45_11hr` | 1,487 |
| `test_opus45_improved_harness` | 1,363 |

## Important Notes

- **Do not modify anything in `tests/`**. The tests are frozen. Validate with `git diff origin/main tests/` to confirm no changes.
- **Kernel results are cached** via `@lru_cache` in the test file, so the kernel only builds and runs once regardless of how many speed tests execute.
- **Output goes to stderr and stdout intermixed**. The `CYCLES: <number>` lines and `Speedup over baseline:` line are printed to stdout by the test helper, while unittest results go to stderr. When capturing output, use `2>&1` to see everything together.
- **Timeout**: A full run takes roughly 3-5 seconds. No special timeout is needed, but a 60-second timeout is a safe upper bound.
- **No dependencies beyond the repo itself**. The tests import from `tests/frozen_problem.py` (the simulator/reference impl) and `perf_takehome.py` (the file being optimized). No pip packages are required.
- **The file you optimize is `perf_takehome.py`**, specifically the `KernelBuilder.build_kernel()` method.

## Reading the Output

A typical run looks like:

```
..FFFFFFF
======================================================================
FAIL: test_kernel_updated_starting_point (...)
...
----------------------------------------------------------------------
Ran 9 tests in 3.4s

FAILED (failures=7)
Testing forest_height=10, rounds=16, batch_size=256
CYCLES:  110871
Speedup over baseline:  1.33
```

- `.` = pass, `F` = fail
- The `CYCLES` number is what matters — lower is better
- `Speedup over baseline` is relative to the original 147,734 cycle baseline
