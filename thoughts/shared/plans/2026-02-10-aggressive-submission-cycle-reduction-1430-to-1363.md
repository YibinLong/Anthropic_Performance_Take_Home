# Aggressive Submission-Path Cycle Reduction (1430 -> <1363) Implementation Plan

## Overview

Reduce kernel cycles from the currently verified `1430` to `<1363` (67-cycle gap) by prioritizing high-upside structural changes in `KernelBuilder.build_kernel()` and high-risk scheduler upgrades. This plan optimizes **submission path only** (`emit_debug=False`) and explicitly keeps `tests/` unchanged.

## Current State Analysis

- Verified baseline: `1430` cycles from `python tests/submission_tests.py`.
- Failing threshold: `assert cycles() < 1363` at `tests/submission_tests.py:115`.
- Active bottlenecks from current diagnostics:
- `valu`: ~93.5% utilization
- `load`: ~90.9% utilization
- `flow`: active/saturated ~41.8% of cycles
- Structural hotspots:
- Gather at depth `>=3` (`load_offset` loop) in `perf_takehome.py:1181`.
- Submission-path compact-state logic at `perf_takehome.py:875` and `perf_takehome.py:876`.
- Single-segment schedule generation in `perf_takehome.py:637` and `perf_takehome.py:1371`.

### Key Discoveries:
- Cycle score is incremented per non-debug bundle in the frozen simulator (`tests/frozen_problem.py:197`, `tests/frozen_problem.py:217`).
- Submission checks final values only (not indices) in `tests/submission_tests.py:45` and `tests/submission_tests.py:52`.
- Current scheduler already includes full WAR-reader tracking and successor-weight priority (`perf_takehome.py:487`, `perf_takehome.py:530`).
- Deterministic-node depth bands exist for depth 3 (`[7..14]`) and depth 4 (`[15..30]`) based on traversal semantics (`tests/frozen_problem.py:535`).

## Desired End State

- `python tests/submission_tests.py` passes all 9 tests.
- `test_opus45_improved_harness` passes with cycles `<1363`.
- `tests/` directory remains byte-for-byte unchanged.
- Submission-path optimizations are stable and reproducible (no seed-dependent flakiness).

### Verification of End State
- `git diff -- tests/` is empty.
- `python tests/submission_tests.py` passes.
- At least 3 repeated runs produce same cycle count and remain `<1363`.

## What We're NOT Doing

- We will not edit any file under `/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home/tests`.
- We will not optimize for debug/trace throughput as a primary objective.
- We will not relax correctness constraints or simulator semantics.
- We will not ship a plan outcome with unresolved technical questions.

## Implementation Approach

Use an aggressive, stage-gated sequence:
1. Lock measurement and guardrails.
2. Attack startup/drain and address-chain serialization in submission path.
3. Replace depth-3 gather with deterministic select path.
4. Attempt depth-4 deterministic/partial deterministic path with strict acceptance gates.
5. Upgrade scheduler strategy beyond current greedy packing.
6. Execute high-risk final pushes until either `<1363` is reached or all defined high-risk options are exhausted with complete evidence.

---

## Phase 1: Measurement Harness + Guardrails

### Overview
Create a deterministic experiment loop so high-risk changes can be accepted/rejected quickly with full correctness and no accidental test edits.

### Changes Required:

#### 1.1 Add a submission-only cycle/evidence runner

**File**: `tools/opt_debug/auto_optimize.py`
**Changes**:
- Add a mode that always runs with frozen submission semantics (`emit_debug=False`, frozen reference check).
- Emit one compact summary per trial: cycles, pass/fail, engine utilization, and key config toggles.

```python
# Pseudocode
result = run_submission_trial(kernel_kwargs)
write_json({"cycles": result.cycles, "correct": result.correct, "config": kernel_kwargs})
```

#### 1.2 Add a no-tests-edits guard check to optimization runs

**File**: `tools/opt_debug/auto_optimize.py`
**Changes**:
- Before and after trial batches, execute `git diff -- tests/` and fail fast if non-empty.

```python
# Pseudocode
assert run("git diff -- tests/").strip() == ""
```

#### 1.3 Capture per-depth attribution hooks

**File**: `perf_takehome.py`
**Changes**:
- Add optional metadata tags in schedule profile for round/depth sections to attribute cycle changes to depths 0/1/2/3+.

### Success Criteria:

#### Automated Verification:
- [x] `git diff -- tests/` returns empty before and after runs.
- [x] `python tests/submission_tests.py` still reports baseline-compatible correctness.
- [x] Trial runner generates per-trial JSON/MD artifacts without failures.

#### Manual Verification:
- [ ] Confirm artifacts make it obvious which phase changed cycles.
- [ ] Confirm measurements are reproducible run-to-run.

**Implementation Note**: After this phase passes, pause for manual confirmation before Phase 2.

---

## Phase 2: Submission-Path Address-Chain De-serialization (Startup + Drain)

### Overview
Reduce startup/drain critical-path bubbles by restructuring address generation and store-back scheduling in submission mode only.

### Changes Required:

#### 2.1 Rework prologue address generation for vector loads

**File**: `perf_takehome.py:1295`
**Changes**:
- Replace strictly serialized per-chunk address materialization patterns with rolling pointer or multi-register address streams.
- Keep semantics identical for values array loads.

```python
# Pseudocode direction
addr0 = base_values_ptr
for each vec chunk:
    vload(chunk, addr0)
    addr0 = addr0 + VLEN
```

#### 2.2 Rework epilogue address generation for vector stores

**File**: `perf_takehome.py:1395`
**Changes**:
- Break flow/store alternating dependency chain by using additional temporary address registers and/or ALU increment path where legal.
- Submission path only (`emit_debug=False`).

#### 2.3 Preserve debug-mode behavior untouched

**File**: `perf_takehome.py`
**Changes**:
- Gate new behavior behind submission-path conditionals; keep debug path as-is.

### Success Criteria:

#### Automated Verification:
- [x] `python tests/submission_tests.py` correctness still passes.
- [x] Cycle-count branch exploration completed; no winning Phase-2 variant found (regression to 1541 in attempted rewrites, then reverted to 1430 baseline). Phase accepted as complete by user direction.
- [x] `python analyze_ops.py` captured startup/drain profile for attempted variants; no improvement found, phase closed by user direction.

#### Manual Verification:
- [ ] Confirm startup/drain sections in diagnostics are shorter or better packed.
- [ ] Confirm no new scratch overflow risk appears.

**Implementation Note**: Phase marked complete by explicit user instruction on 2026-02-10 despite no net cycle improvement; proceed to Phase 3.

---

## Phase 3: Depth-3 Deterministic No-Gather Path

### Overview
Replace depth-3 gather (`load_offset` fanout) with deterministic selection from preloaded nodes 7..14 in submission mode.

### Changes Required:

#### 3.1 Preload depth-3 deterministic node set

**File**: `perf_takehome.py` (header construction around node preload near `perf_takehome.py:931`)
**Changes**:
- Add scalar + vector preload for nodes `7..14` with strict scratch budgeting.

#### 3.2 Add `depth == 3` specialized emit path

**File**: `perf_takehome.py:1060`
**Changes**:
- Split current `else` gather branch into explicit `elif depth == 3` and `else` (`depth >= 4`) branches.
- Implement deterministic select tree for depth-3 node value materialization.

```python
# Pseudocode direction
path3 = idx - 7
b0,b1,b2 = bit_extract(path3)
node_val = select_tree(nodes7_14, b0,b1,b2)
```

#### 3.3 Keep fallback and safety toggle

**File**: `perf_takehome.py` (`KernelBuilder.__init__`)
**Changes**:
- Add configurable switch (default ON once validated) for depth-3 specialized path to allow quick rollback during tuning.

### Success Criteria:

#### Automated Verification:
- [ ] `python tests/submission_tests.py` passes correctness and speed gates up to current best.
- [ ] Cycle count improves materially versus post-Phase-2 baseline.
- [ ] Engine pressure shows lower load pressure than before phase.

#### Manual Verification:
- [ ] Confirm depth-3 rounds no longer emit gather-heavy pattern.
- [ ] Confirm scratch usage remains below `SCRATCH_SIZE` with margin.

**Implementation Note**: After this phase passes, pause for manual confirmation before Phase 4.

---

## Phase 4: Depth-4 Aggressive Deterministic/Hybrid Path

### Overview
Attempt higher-risk depth-4 optimization to remove additional gather cost, accepting larger implementation complexity and rollback risk.

### Changes Required:

#### 4.1 Implement depth-4 experimental mode

**File**: `perf_takehome.py:1060`
**Changes**:
- Add `depth == 4` branch with one aggressive strategy:
- full deterministic select from preloaded `15..30`, or
- hybrid two-stage deterministic path with bounded temporary usage.

#### 4.2 Add scratch-budget-aware interleave adaptation

**File**: `perf_takehome.py` (interleave/group allocation near `perf_takehome.py:1012`)
**Changes**:
- Dynamically adjust interleave groups in submission mode if depth-4 preloads increase scratch pressure.
- Keep config explicit and measurable.

#### 4.3 Add acceptance gate and rollback condition

**File**: `perf_takehome.py` + `tools/opt_debug/auto_optimize.py`
**Changes**:
- Keep depth-4 mode optional until it beats the best stable cycle count with correctness intact.

### Success Criteria:

#### Automated Verification:
- [ ] Full `python tests/submission_tests.py` pass.
- [ ] Net cycle improvement over Phase-3 best.
- [ ] No increase in correctness flakiness across repeated runs.

#### Manual Verification:
- [ ] Confirm changed scratch/interleave config is documented in run artifacts.
- [ ] Confirm improvement is robust, not a one-off measurement artifact.

**Implementation Note**: After this phase passes, pause for manual confirmation before Phase 5.

---

## Phase 5: Scheduler Upgrade Beyond Greedy Packing

### Overview
Increase bundle quality with more aggressive scheduling strategies once structural changes have shifted dependency geometry.

### Changes Required:

#### 5.1 Add multi-start deterministic scheduler search

**File**: `perf_takehome.py:456`
**Changes**:
- For submission mode, run `_schedule_vliw` with a deterministic seed set and keep the shortest non-debug schedule.

```python
# Pseudocode
best = inf
for seed in seed_list:
    sched = schedule_with_seed(seed)
    best = min(best, sched, key=non_debug_cycles)
```

#### 5.2 Add limited lookahead/beam packing mode

**File**: `perf_takehome.py:456`
**Changes**:
- Add optional beam-width packer that scores candidate bundles by projected next-cycle slot fill.
- Keep default fallback to current greedy scheduler for safety.

#### 5.3 Add scheduler profiling output for decision traceability

**File**: `perf_takehome.py`, `tools/opt_debug/analyze_schedule.py`
**Changes**:
- Emit selected seed/mode and cycle deltas to diagnostics artifacts.

### Success Criteria:

#### Automated Verification:
- [ ] Submission tests pass with selected scheduler mode.
- [ ] Chosen scheduler mode consistently beats prior best cycles.
- [ ] Build-time overhead remains acceptable (kernel build still practical for repeated tests).

#### Manual Verification:
- [ ] Confirm selected scheduler mode is deterministic and reproducible.
- [ ] Confirm fallback mode is preserved for fast rollback.

**Implementation Note**: After this phase passes, pause for manual confirmation before Phase 6.

---

## Phase 6: Final High-Risk Push Until Target

### Overview
Keep executing high-risk experiments (submission-only) until `<1363` is reached or all defined aggressive options are exhausted with hard evidence.

### Changes Required:

#### 6.1 High-risk experiment queue (ordered)

**Files**: `perf_takehome.py`, `tools/opt_debug/auto_optimize.py`
**Changes**:
- Run and evaluate, in order:
1. depth-3 mode variants (flow-tree vs arithmetic select variants)
2. depth-4 variants with adaptive interleave
3. scheduler beam widths / seed sets
4. combined structural + scheduler configurations

#### 6.2 Keep only dominant configurations

**Files**: `perf_takehome.py`, `docs/OPTIMIZATION_MASTER_SUMMARY.md`
**Changes**:
- Remove or disable dominated configs.
- Document winner config, rejected paths, and measured deltas.

### Success Criteria:

#### Automated Verification:
- [ ] `python tests/submission_tests.py` passes all tests.
- [ ] `CYCLES` is `<1363`.
- [ ] `git diff -- tests/` remains empty.

#### Manual Verification:
- [ ] Confirm winning config is clearly documented and reproducible.
- [ ] Confirm no experimental dead code remains in final selected path.

**Implementation Note**: After this phase and verification, stop and present final result summary.

---

## Testing Strategy

### Unit Tests:
- `python tests/submission_tests.py CorrectnessTests`
- `python perf_takehome.py Tests.test_kernel_cycles`

### Integration Tests:
- `python tests/submission_tests.py`
- Repeat full submission run 3 times for reproducibility.

### Manual Testing Steps:
1. Run full submission tests and capture `CYCLES`.
2. Run diagnostics (`do_kernel_test(..., diagnostics_out=...)`) and inspect engine pressure.
3. Confirm `git diff -- tests/` is empty after each phase.

## Performance Considerations

- Current hard pressure is dual-engine (`valu` + `load`), so winning changes must reduce either:
- hot-path VALU op count, or
- depth-3+/depth-4 gather load footprint, or
- scheduling overhead over the existing lower bound.
- Flow is not currently the primary limiting engine, but flow-chain serialization can still harm critical path in startup/drain and deterministic select trees.
- Scratch headroom must be actively managed when adding deterministic-node preloads and temporary vectors.

## Migration Notes

- No external migrations required.
- No API/schema/data-format changes.
- This is an internal kernel/scheduler optimization-only effort.

## References

- Primary optimization target: `perf_takehome.py:780`
- Scheduler core: `perf_takehome.py:456`
- Gather hotspot: `perf_takehome.py:1181`
- Submission threshold check: `tests/submission_tests.py:115`
- Cycle accounting semantics: `tests/frozen_problem.py:197`, `tests/frozen_problem.py:217`
- Current optimization status: `docs/OPTIMIZATION_MASTER_SUMMARY.md`
- Run instructions and constraints: `Readme.md`, `docs/running-tests.md`
- Prior plan context: `thoughts/shared/plans/2026-02-10-cycle-reduction-1446-to-1363.md`
- Prior research context: `thoughts/shared/research/2026-02-10-cycle-optimization-context-map.md`
