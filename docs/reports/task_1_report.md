# Task One Report: VLIW Scheduler / Slot Packer (Full Implementation)

## Goal
Implement the “real VLIW scheduler / slot packer” from `C_improvements.md`:
pack independent ops into the same cycle while respecting engine slot limits
and RAW/WAW hazards, allowing WAR in the same cycle.

## What Changed
- Implemented a dependency-based list scheduler in `KernelBuilder._schedule_vliw`.
  - **Strict deps** (RAW, WAW): successor must be in a later cycle.
  - **Weak deps** (WAR): successor can be in the same cycle *after* the read.
  - Uses per-engine `SLOT_LIMITS` to fill bundles.
- Added barrier handling so control-flow ops (`pause`, `jump`, `cond_jump`, etc.)
  are not reordered across.
- Added `emit_debug` flag to `KernelBuilder` (default `False`) so debug-only
  slots can be omitted from the packed schedule and don’t add cycles.
  - `KernelBuilder.add` now skips debug slots when `emit_debug=False`.
  - `KernelBuilder.build` filters debug slots when `emit_debug=False`.

## Why This Matches Task 1
The scheduler now:
- Builds per-slot read/write sets.
- Enforces RAW/WAW constraints, while allowing WAR **only within the same cycle**.
- Actively reorders independent ops to maximize slot usage.
- Emits packed bundles instead of one-slot-per-cycle bundles.

## Tests Run
From repo root:
```
python tests/submission_tests.py
```

## Results
- **Correctness**: Passed.
- **Speed**:
  - Observed cycle count: **13,391**
  - Baseline speedup: **~11.03x**
  - Passed `test_kernel_speedup` (baseline) and `test_kernel_updated_starting_point` (18,532).
  - Failed the more aggressive Opus/Sonnet thresholds (expected for Task 1 only).

### Failures (expected for Task 1)
The following performance thresholds still fail and require additional
optimizations beyond Task 1:
- `test_opus4_many_hours` (< 2,164)
- `test_opus45_casual` (< 1,790)
- `test_opus45_2hr` (< 1,579)
- `test_sonnet45_many_hours` (< 1,548)
- `test_opus45_11hr` (< 1,487)
- `test_opus45_improved_harness` (< 1,363)

## Notes / Next Improvements (Out of Scope)
To reach sub-2k thresholds, additional items from `C_improvements.md`
are required (e.g., flow-select elimination, pipelining, scratch reuse).
