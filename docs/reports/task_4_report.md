# Task 4 Report - Hash Stage Pair/Combine Parallelism

## Summary
Implemented hash-stage pair/combine parallelism so the two independent hash ops (op1/op3) are issued together, with the combine op scheduled separately. This aligns with IMPROVEMENTS_C task 4 and enables a 2-cycle-per-stage structure while still allowing other work to fill unused VALU slots.

## What Changed
- **File:** `perf_takehome.py`
- **Functions:** `KernelBuilder.build_hash`, `KernelBuilder.build_hash_vec`, `_schedule_vliw`, and `build`
- **Core change:** Hash stages now emit a *paired* op group for op1/op3 and a separate combine op. The VLIW scheduler was extended to treat grouped same-engine slots as an atomic unit that consumes multiple engine slots in a single cycle.

## Rationale
Each hash stage computes:
```
tmp1 = a OP1 const1
tmp2 = a OP3 const3
a    = tmp1 OP2 tmp2
```
The first two ops are independent, so they can execute in the same cycle. By emitting them as a grouped VALU/ALU pair, the scheduler can place them together while still interleaving other groups to fill remaining slots.

## Tests Run
Command (per `docs/running-tests.md`):
```
python tests/submission_tests.py 2>&1
```

## Test Results
- **Correctness:** Passed (kernel correctness test succeeded).
- **Performance:** Several stricter speed thresholds still failed (expected without additional optimizations).
- **Observed cycles:** `2660` for `forest_height=10, rounds=16, batch_size=256`.
- **Speedup over baseline:** `~55.54x` (reported by the harness).

## Notes
- Cycle count remained the same as before this change, which suggests the scheduler was already able to co-schedule these ops most of the time. The grouping change makes that pairing explicit and robust.
- No other optimizations (flow select removal, multiply_add, etc.) were touched, per the “only task 4” constraint.
