---
date: "2026-02-10T13:26:58Z"
researcher: work
git_commit: 3ec5dde7dc1f59902fb6198fd69238fb1f065654
branch: main
repository: Anthropic_Performance_Take_Home
topic: "VLIW Kernel Optimization Codebase Research — System Architecture, Current State, and Relevant Files"
tags: [research, codebase, vliw, kernel, optimization, performance, scheduler]
status: complete
last_updated: "2026-02-10"
last_updated_by: work
---

# Research: VLIW Kernel Optimization Codebase — Full System Architecture

**Date**: 2026-02-10T13:26:58Z
**Researcher**: work
**Git Commit**: 3ec5dde7dc1f59902fb6198fd69238fb1f065654
**Branch**: main
**Repository**: Anthropic_Performance_Take_Home

## Research Question
How does the system work end-to-end, what is its current performance state, and which files + line numbers are relevant for continuing cycle-count optimization?

## Summary

The codebase implements a **VLIW SIMD kernel** that performs parallel binary-tree traversal with hashing on a custom simulated machine. The kernel processes 256 inputs through 16 rounds on a height-10 tree (2047 nodes). The current implementation achieves **1446 cycles** (102.17x speedup over the 147,734-cycle baseline), passing 8/9 submission tests. The only failing test requires < 1363 cycles (83 cycles to go). The kernel is dual-bottlenecked on **VALU (92.5% utilization)** and **load (91.7%)**, with **flow saturated 35.4%** of cycles.

---

## Detailed Findings

### 1. Simulated Machine Architecture

**File**: [`problem.py`](https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/3ec5dde7dc1f59902fb6198fd69238fb1f065654/problem.py)

The machine is a single-core VLIW SIMD processor defined at `problem.py:48-59`:

| Constant | Value | Location |
|----------|-------|----------|
| `SLOT_LIMITS` | `{alu:12, valu:6, load:2, store:2, flow:1, debug:64}` | `problem.py:48-55` |
| `VLEN` | `8` | `problem.py:57` |
| `N_CORES` | `1` | `problem.py:59` |
| `SCRATCH_SIZE` | `1536` | `problem.py:60` |

**Execution model** (`Machine` class, `problem.py:64-402`):
- Each cycle, all engines execute their filled slots **in parallel** (`problem.py:352-387`)
- Writes take effect **at end of cycle** — write-after-read within the same cycle is safe (`problem.py:388-391`)
- Debug slots are ignored in submission mode (`problem.py:367-368`)
- Cycle is counted only if the instruction has at least one non-debug engine (`problem.py:214-217`)

**Engine operations**:
- **ALU** (`problem.py:219-252`): Scalar arithmetic — `+`, `-`, `*`, `//`, `^`, `&`, `|`, `<<`, `>>`, `%`, `<`, `==`. All results mod 2^32.
- **VALU** (`problem.py:254-267`): Vector ops on VLEN=8 elements — `vbroadcast`, `multiply_add` (fused `a*b+c`), and all ALU ops applied per-lane.
- **Load** (`problem.py:269-286`): `load` (scalar), `load_offset` (gather with static offset), `vload` (contiguous 8-element), `const` (immediate).
- **Store** (`problem.py:288-298`): `store` (scalar), `vstore` (contiguous 8-element).
- **Flow** (`problem.py:300-335`): `select`, `vselect` (per-lane conditional), `add_imm`, `halt`, `pause`, jumps. **Only 1 slot/cycle**.

### 2. The Algorithm (Reference Kernel)

**File**: [`problem.py:467-484`](https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/3ec5dde7dc1f59902fb6198fd69238fb1f065654/problem.py#L467-L484) (reference_kernel) and [`problem.py:535-568`](https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/3ec5dde7dc1f59902fb6198fd69238fb1f065654/problem.py#L535-L568) (reference_kernel2)

Per round, per batch element:
1. `node_val = tree[idx]` — memory lookup
2. `val = myhash(val ^ node_val)` — 6-stage hash
3. `idx = 2*idx + (1 if val%2==0 else 2)` — branch decision
4. `idx = 0 if idx >= n_nodes else idx` — wrap at tree bottom

**Tree structure** (`problem.py:405-418`): Perfect balanced binary tree; height 10 = 2047 nodes.

**Input** (`problem.py:422-436`): 256 elements, all starting at idx=0.

### 3. Hash Function

**HASH_STAGES** (`problem.py:439-446`): 6 stages, each computing `a = op2(op1(a, val1), op3(a, val3))` mod 2^32.

| Stage | op1 | val1 | op2 | op3 | val3 |
|-------|-----|------|-----|-----|------|
| 0 | `+` | `0x7ED55D16` | `+` | `<<` | 12 |
| 1 | `^` | `0xC761C23C` | `^` | `>>` | 19 |
| 2 | `+` | `0x165667B1` | `+` | `<<` | 5 |
| 3 | `+` | `0xD3A2646C` | `^` | `<<` | 9 |
| 4 | `+` | `0xFD7046C5` | `+` | `<<` | 3 |
| 5 | `^` | `0xB55A4F09` | `^` | `>>` | 16 |

**Scalar hash** (`perf_takehome.py:689-705`): Emits 2 ALU ops per stage (parallel pair + combine) = 12 ALU ops total.

**Vector hash** (`perf_takehome.py:707-758`): Three optimization paths per stage:

| Stage | Pattern | Path | VALU ops | Lines |
|-------|---------|------|----------|-------|
| 0 | `+ + <<` | Full simplification: single `multiply_add` | 1 | `711-721` |
| 1 | `^ ^ >>` | No simplification: parallel pair + combine | 2 | `733-743` |
| 2 | `+ + <<` | Full simplification: single `multiply_add` | 1 | `711-721` |
| 3 | `+ ^ <<` | No simplification (op2 is `^` not `+`) | 2 | `733-743` |
| 4 | `+ + <<` | Full simplification: single `multiply_add` | 1 | `711-721` |
| 5 | `^ ^ >>` | No simplification: parallel pair + combine | 2 | `733-743` |
| **Total** | | | **9** | |

Note: Stage 3 takes Path 3 (else branch) because while `op1=="+"` and `op3=="<<"`, `op2=="^"` (not `"+"`), so it doesn't match either simplification branch.

### 4. KernelBuilder — The Optimization Target

**File**: [`perf_takehome.py:267-1376`](https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/3ec5dde7dc1f59902fb6198fd69238fb1f065654/perf_takehome.py#L267-L1376)

**Constructor parameters** (lines 268-296):
```
interleave_groups = 25       # Groups for depth 3+
interleave_groups_early = 29 # Groups for depths 0-2
depth2_select_mode = "flow_vselect"
idx_branch_mode = "flow_vselect"
scheduler_crit_weight = 1024
```

**Key pipeline methods**:

| Method | Lines | Purpose |
|--------|-------|---------|
| `_optimize_slots` | `415-448` | Backward-pass dead code elimination |
| `_schedule_vliw` | `450-619` | Dependency-aware VLIW instruction packing |
| `build` | `621-666` | Splits at barriers, runs optimize + schedule per segment |
| `build_kernel` | `760-1376` | Emits all kernel operations |
| `build_hash` | `689-705` | Scalar hash emission |
| `build_hash_vec` | `707-758` | Vector hash emission with algebraic fusion |

### 5. VLIW Scheduler

**File**: `perf_takehome.py:450-619`

**Dependency tracking** (lines 471-497):
- **Strict dependencies** (RAW, WAW): Successor must schedule at cycle C+1 or later (line 549)
- **Weak dependencies** (WAR): Successor must schedule after cycle C (line 552, no +1)
- Uses arrays `last_write[SCRATCH_SIZE]` and `last_read[SCRATCH_SIZE]` for tracking

**Critical path computation** (lines 501-514): Longest-path-to-terminal for each op, computed in reverse topological order.

**Priority** (lines 516-521): `crit_path[i] * scheduler_crit_weight + engine_bias[engine]`

**Scheduling loop** (lines 538-594): Greedy list scheduling — pops highest-priority ready ops, checks timing constraints and slot limits, defers what doesn't fit.

### 6. build_kernel Body Structure

**File**: `perf_takehome.py:760-1376`

#### Submission-path flags (lines 849-855):
```python
use_idx_mem = self.emit_debug           # False in submission
use_compact_depth_state = (not self.emit_debug and depth2_select_mode == "flow_vselect")  # True
need_wrap_checks = self.emit_debug      # False in submission
```

#### Header (lines 845-966):
- Loads pointers from memory header (forest_values_p, inp_values_p)
- Allocates scalar/vector constants (0, 1, 2, 7, hash constants)
- Preloads tree nodes 0-6 into scalar registers then broadcasts to vectors (`vec_node0` through `vec_node6`)
- In non-debug mode, merged into body for joint VLIW scheduling (line 1002)

#### Interleave groups (lines 1009-1021):
- Allocates `max(25, 29) = 29` register groups, each with 3 VLEN-sized scratch regions
- Depths 0-2 use 29 groups; depths 3+ use 25 groups (line 1303-1307)
- Each group gets `vec_node_val`, `vec_addr`, `vec_val_save` temporaries

#### Batch loading (lines 1264-1299):
- Pre-allocates offset constants into body (line 1277)
- Vector loads values (and indices if debug) for 256/8 = 32 vector chunks
- Uses `tmp_addr` / `tmp_addr_b` for address computation

#### Main loop (lines 1301-1347):
- 16 rounds, depth = `round % 11` (forest_height=10, so depth cycles 0-10)
- Per round: iterates vector chunks in groups of `VLEN * num_groups`
- Calls `emit_vector_group_ops(round, i, regs, depth)` per group

#### emit_vector_group_ops (lines 1029-1262):

| Depth | Node Selection | Hash | Idx Update | Key Lines |
|-------|---------------|------|------------|-----------|
| 0 | XOR with preloaded `vec_node0` | 9 VALU ops | Store bit b0 in `vec_idx` (compact) | 1051-1068, 1189-1192 |
| 1 | `vselect` node1/node2 by b0 | 9 VALU ops | Build path `2*b0+b1` (compact) | 1069-1096, 1194-1198 |
| 2 | 3-vselect from nodes 3-6 by path bits | 9 VALU ops | Materialize idx `7+2*path+b2` (compact) | 1097-1148, 1200-1205 |
| 3+ | Gather via `load_offset` (8 loads) | 9 VALU ops | Full `multiply_add(idx, idx, 2, branch)` | 1149-1170, 1217-1227 |

**Submission-path skip** (line 1186-1187): Skips idx update when `depth == forest_height` or `round == rounds-1`.

#### Epilogue (lines 1349-1370):
- Vector stores values back to memory
- Skips index stores in submission mode

#### Final assembly (lines 1371-1375):
- Calls `self.build(body, vliw=True)` to schedule the entire body as one VLIW segment (line 1371)

### 7. Test Infrastructure

**Submission tests**: [`tests/submission_tests.py`](https://github.com/YibinLongTrilogy/Anthropic_Performance_Take_Home/blob/3ec5dde7dc1f59902fb6198fd69238fb1f065654/tests/submission_tests.py)

| Test | Threshold | Status |
|------|-----------|--------|
| `test_kernel_speedup` | < 147,734 | PASS |
| `test_kernel_updated_starting_point` | < 18,532 | PASS |
| `test_opus4_many_hours` | < 2,164 | PASS |
| `test_opus45_casual` | < 1,790 | PASS |
| `test_opus45_2hr` | < 1,579 | PASS |
| `test_sonnet45_many_hours` | < 1,548 | PASS |
| `test_opus45_11hr` | < 1,487 | PASS |
| `test_opus45_improved_harness` | < 1,363 | **FAIL (1446)** |

**Correctness test**: `tests/submission_tests.py:57-60` — runs `do_kernel_test(10, 16, 256)` with 8 different random seeds, using frozen simulator from `tests/frozen_problem.py`.

**Key**: Submission tests use `KernelBuilder()` with **no arguments** (all defaults) at `tests/submission_tests.py:25`.

### 8. Current Bottleneck Profile

From `docs/OPTIMIZATION_MASTER_SUMMARY.md`:

| Engine | Utilization | Status |
|--------|------------|--------|
| `valu` | 92.5% | Near saturation |
| `load` | 91.7% | Near saturation |
| `flow` | saturated 35.4% of cycles | 1 slot/cycle limit |
| `alu` | ~10-15% | Mostly idle |
| `store` | low | Mostly idle |

### 9. Optimization History Summary

**Three phases of optimization** took the kernel from 147,734 to 1,446 cycles:

1. **Foundation** (→ 2,177): VLIW scheduling, SIMD vectorization, gather, interleaving, batch-in-scratch
2. **Depth exploitation** (→ 1,486): Depth-aware gather elimination for depths 0-2, interleave tuning, algebraic rewrites, flow-branch select
3. **Micro-optimizations** (→ 1,446): Compact depth state, idx traffic elimination, dead-setup pruning

**Reverted/failed attempts**: Root node caching, depth-2 full flow-select tree, depth-3 compact state (regressed to ~1681), vector address precompute, extensive parameter sweeps.

---

## Code References

### Core Files
- `perf_takehome.py:267-296` — KernelBuilder constructor and parameters
- `perf_takehome.py:415-448` — Dead code elimination (_optimize_slots)
- `perf_takehome.py:450-619` — VLIW scheduler (_schedule_vliw)
- `perf_takehome.py:621-666` — Build pipeline with barrier segmentation
- `perf_takehome.py:689-705` — Scalar hash builder (build_hash)
- `perf_takehome.py:707-758` — Vector hash builder with algebraic fusion (build_hash_vec)
- `perf_takehome.py:760-1376` — Main kernel builder (build_kernel)
- `perf_takehome.py:845-966` — Header: pointer loads, constant allocation, node preloading
- `perf_takehome.py:1009-1021` — Interleave group allocation
- `perf_takehome.py:1029-1262` — emit_vector_group_ops (per-depth logic)
- `perf_takehome.py:1264-1299` — Batch data loading into scratch
- `perf_takehome.py:1301-1347` — Main round loop with interleaved group emission
- `perf_takehome.py:1349-1376` — Epilogue: store-back and VLIW build

### Architecture Definition
- `problem.py:48-60` — SLOT_LIMITS, VLEN, N_CORES, SCRATCH_SIZE
- `problem.py:64-402` — Machine simulator
- `problem.py:219-252` — ALU operations
- `problem.py:254-267` — VALU operations (including multiply_add)
- `problem.py:269-286` — Load operations (including load_offset, vload)
- `problem.py:300-335` — Flow operations (including vselect)
- `problem.py:439-446` — HASH_STAGES constant

### Algorithm Reference
- `problem.py:467-484` — reference_kernel (high-level)
- `problem.py:535-568` — reference_kernel2 (memory-level, used for validation)
- `problem.py:487-513` — build_mem_image (memory layout)

### Test Infrastructure
- `tests/submission_tests.py:24-27` — kernel_builder (default params, cached)
- `tests/submission_tests.py:30-54` — do_kernel_test (correctness check)
- `tests/submission_tests.py:66-73` — cycles() (cached cycle measurement)
- `tests/submission_tests.py:76-115` — SpeedTests (8 threshold levels)

### Documentation
- `docs/OPTIMIZATION_MASTER_SUMMARY.md` — Comprehensive optimization history and analysis

---

## Architecture Documentation

### Operation Count Per Batch Element Per Round

For a depth-0 round (compact state, submission mode):
- **Node selection**: 0 VALU ops (direct XOR with preloaded constant)
- **XOR**: 1 VALU op
- **Hash**: 9 VALU ops
- **Idx update**: 1 VALU op (store bit)
- **Total**: ~11 VALU ops per element

For a depth-3+ round (gather, submission mode, not final):
- **Gather address**: 1 VALU op
- **Gather loads**: 8 load ops (via load_offset)
- **XOR**: 1 VALU op
- **Hash**: 9 VALU ops
- **Idx update**: ~3 VALU ops + 1 flow op (branch + multiply_add)
- **Total**: ~14 VALU ops + 8 loads + 1 flow per element

### Theoretical Work Per Full Run

- 16 rounds × 256 elements = 4096 element-rounds
- Depths cycle: 0,1,2,3,4,5,6,7,8,9,10,0,1,2,3,4 (rounds 0-15 with height 10)
- 3 early depths (0,1,2) appear in rounds 0-2 and 11-13 = 6 rounds
- 8 gather depths (3-10) appear in rounds 3-10 = 8 rounds
- 2 mixed-wrap depths (round 15 = depth 4, round 10 = depth 10)

### Scratch Space Usage

- Header pointers: ~5-8 words
- Scalar constants: varies with dedup
- Vector constants: 8 words each (VLEN), multiple hash constants + structural constants
- Node broadcasts: 7 × 8 = 56 words (vec_node0 through vec_node6)
- Interleave group registers: 29 groups × 3 vectors × 8 = 696 words
- Batch arrays: idx_arr (256) + val_arr (256) = 512 words
- Offset constants: ~32 words
- Total: approaching SCRATCH_SIZE = 1536

---

## Open Questions

1. **Stage 3 of the hash** (`("+", 0xD3A2646C, "^", "<<", 9)`): Takes the unoptimized path because `op2 == "^"` not `"+"`. Is there an algebraic rewrite that could fuse this into fewer VALU ops?

2. **Depth-3+ gather operations**: Each requires 8 `load_offset` ops (one per VLEN lane) but the load engine only has 2 slots/cycle, requiring at least 4 cycles just for the gather. What are alternatives?

3. **Scratch space pressure**: At 29 interleave groups the scratch is nearly full. Could register reuse across non-overlapping phases free space for more groups?

4. **Flow engine saturation at 35.4%**: The compact depth-state mode uses 3 vselect ops for depth-2. Could an arithmetic approach avoid flow entirely for some depths?

5. **The gap between theoretical minimum (~1334) and current (1446)**: Where exactly do the ~112 extra cycles come from? Scheduler sub-optimality, pipeline bubbles, or structural inefficiency?
