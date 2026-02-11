---
date: 2026-02-10T13:16:03-05:00
researcher: work
git_commit: f928f631c54279bf73138b68a8d9601a9f9d73f5
branch: main
repository: Anthropic_Performance_Take_Home
topic: "Optimization context from prompts/continue_optimization_4.md and cycle-critical code paths"
tags: [research, codebase, optimization, perf_takehome, submission-tests, scheduler]
status: complete
last_updated: 2026-02-10
last_updated_by: work
---

# Research: Optimization Context from `prompts/continue_optimization_4.md`

**Date**: 2026-02-10T13:16:03-05:00  
**Researcher**: work  
**Git Commit**: `f928f631c54279bf73138b68a8d9601a9f9d73f5`  
**Branch**: `main`  
**Repository**: `Anthropic_Performance_Take_Home`

## Research Question
We are working on optimizations described in `prompts/continue_optimization_4.md`. Read that file and research how the current system works, including which files and line numbers are relevant to reducing cycle count, without producing a fix plan.

## Summary
The optimization prompt is explicit: continue optimization work based on `Readme.md` and reduce cycles in `perf_takehome.py` (`prompts/continue_optimization_4.md:3`).  
Cycle targets and pass/fail gates are defined by `tests/submission_tests.py`, with the strictest speed threshold at `< 1363` cycles (`tests/submission_tests.py:115`).  
The implementation under optimization is `KernelBuilder.build_kernel()` in `perf_takehome.py` (`perf_takehome.py:780`), and cycle count comes from simulator execution in `Machine.run()` where `self.cycle` increments once per non-debug instruction bundle (`tests/frozen_problem.py:197`, `tests/frozen_problem.py:217`).

## Detailed Findings

### 1. Optimization Goal Definition
- Prompt objective is to reduce cycle count in `perf_takehome.py`: `prompts/continue_optimization_4.md:3` (local working-tree file).
- Benchmark context and threshold narrative are in `Readme.md:13`, `Readme.md:18`, `Readme.md:21`.
- Tests command and anti-cheating constraints are documented in `Readme.md:23`, `Readme.md:27`, `Readme.md:29`.
- Running-tests guide maps the official target file to `KernelBuilder.build_kernel()` in `perf_takehome.py` (`docs/running-tests.md:43`).

### 2. Official Cycle Thresholds and Assertions
- Kernel build path used by tests: `tests/submission_tests.py:23` to `tests/submission_tests.py:27`.
- End-to-end test runner that prints and returns cycle count: `tests/submission_tests.py:30` to `tests/submission_tests.py:54`.
- Cached cycle measurement helper: `tests/submission_tests.py:66` to `tests/submission_tests.py:73`.
- Threshold assertions:
  - `BASELINE` reference: `tests/submission_tests.py:63`
  - `< 18532`: `tests/submission_tests.py:90`
  - `< 2164`: `tests/submission_tests.py:94`
  - `< 1790`: `tests/submission_tests.py:99`
  - `< 1579`: `tests/submission_tests.py:103`
  - `< 1548`: `tests/submission_tests.py:107`
  - `< 1487`: `tests/submission_tests.py:111`
  - `< 1363`: `tests/submission_tests.py:115`

### 3. End-to-End Runtime Flow (What Is Executed)
1. Tests generate forest/input/memory via frozen helpers (`tests/submission_tests.py:33`, `tests/submission_tests.py:35`; `tests/frozen_problem.py:487`).
2. Tests construct kernel with `KernelBuilder.build_kernel(...)` (`tests/submission_tests.py:25`, `tests/submission_tests.py:26`).
3. Frozen simulator runs program (`tests/submission_tests.py:40`, `tests/submission_tests.py:43`; `tests/frozen_problem.py:197`).
4. Correctness compares final values against `reference_kernel2` final memory (`tests/submission_tests.py:45`, `tests/submission_tests.py:52`; `tests/frozen_problem.py:535`).
5. Speed tests assert threshold comparisons against cached cycle result (`tests/submission_tests.py:76`, `tests/submission_tests.py:115`).

### 4. Cycle Accounting Semantics (Scoring Behavior)
- Frozen simulator initializes cycle counter at zero (`tests/frozen_problem.py:115`).
- During `run()`, each iteration processes current bundle(s); if any engine in bundle is non-debug, cycle increments by 1 (`tests/frozen_problem.py:214`, `tests/frozen_problem.py:217`).
- Debug-only bundles do not contribute to cycle count under this condition.
- Main simulator (`problem.py`) mirrors the same cycle semantics (`problem.py:115`, `problem.py:214`, `problem.py:217`).

### 5. `perf_takehome.py` Areas Directly Connected to Cycle Outcomes
- Task statement and optimize target (`KernelBuilder.build_kernel`) in file header:
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L9
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L13
- KernelBuilder configuration knobs:
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L267
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L280
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L302
- Slot read/write modeling and optimizer:
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L310
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L421
- VLIW scheduler and dependency handling:
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L456
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L478
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L565
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L612
- Build pipeline, segmentation, barrier handling:
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L400
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L637
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L661
- Hash emitters (scalar/vector):
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L705
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L723
- Main kernel body construction:
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L780
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L865
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L1060
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L1181
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L1295
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L1347
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L1395
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L1430
- Harness entrypoint for local cycle runs and diagnostics:
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L1438
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L1510
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/perf_takehome.py#L1582

### 6. Supporting Documentation in This Repository
- Running tests and threshold table:
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/docs/running-tests.md#L23
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/docs/running-tests.md#L43
- Consolidated optimization status document:
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/docs/OPTIMIZATION_MASTER_SUMMARY.md#L7
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/docs/OPTIMIZATION_MASTER_SUMMARY.md#L44
  - https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/f928f631c54279bf73138b68a8d9601a9f9d73f5/docs/OPTIMIZATION_MASTER_SUMMARY.md#L153

## Code References
- `prompts/continue_optimization_4.md:3` - Direct objective to reduce cycles in `perf_takehome.py` (local working tree).
- `Readme.md:23` - Points to `python tests/submission_tests.py` for threshold validation.
- `tests/submission_tests.py:23` - Cached kernel builder helper.
- `tests/submission_tests.py:53` - Prints `CYCLES`.
- `tests/submission_tests.py:115` - Strictest submission threshold (`< 1363`).
- `tests/frozen_problem.py:197` - Simulator run loop.
- `tests/frozen_problem.py:217` - Cycle increment condition.
- `perf_takehome.py:456` - VLIW scheduler implementation.
- `perf_takehome.py:637` - Build pipeline with segment scheduling.
- `perf_takehome.py:780` - `build_kernel` entry.
- `perf_takehome.py:1060` - Vector group emission logic.
- `perf_takehome.py:1438` - Main kernel test harness.

## Architecture Documentation
The active optimized path builds a vectorized kernel and schedules slot operations through a custom VLIW scheduler. The scheduler computes dependencies and priorities, then emits cycle bundles subject to per-engine slot limits (`perf_takehome.py:456`, `perf_takehome.py:573`).  
Submission scoring uses the frozen simulator and frozen reference kernel (`tests/submission_tests.py:11`, `tests/frozen_problem.py:535`).  
Cycle count used by speed tests is the simulator’s `machine.cycle` after full program execution (`tests/submission_tests.py:53`, `tests/submission_tests.py:67`).

## Related Research
- `thoughts/shared/research/2026-02-10-vliw-kernel-optimization-codebase.md`

## Open Questions
- None added in this pass; this document focuses on current-state mapping and references only.
