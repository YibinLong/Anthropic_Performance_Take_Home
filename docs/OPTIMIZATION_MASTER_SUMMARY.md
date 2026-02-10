# Optimization Master Summary

> **Purpose:** Single-file briefing for any agent continuing optimization work on this VLIW kernel. Read this instead of the 30+ individual reports.

## The Problem

We are optimizing a **VLIW SIMD kernel** that performs parallel tree traversal on a custom simulated architecture. The kernel processes a batch of 256 inputs through 16 rounds on a binary tree of height 10 (2047 nodes).

**Each round per batch element:**
1. Look up `node_val = tree[idx]` (memory gather)
2. `val = myhash(val ^ node_val)` (6-stage hash, each stage = 2-3 ops)
3. `idx = 2*idx + (1 if val%2==0 else 2)` (branch decision)
4. Wrap `idx` if it falls off the tree

**Architecture constraints (SLOT_LIMITS per cycle):**
| Engine | Slots/cycle | Notes |
|--------|------------|-------|
| `alu` | 12 | Scalar arithmetic |
| `valu` | 6 | Vector arithmetic (VLEN=8) |
| `load` | 2 | Memory/const loads |
| `store` | 2 | Memory stores |
| `flow` | 1 | Select, jump, vselect |
| `debug` | 64 | Debug only, ignored in submission |

**Key ISA features:**
- `multiply_add(dest, a, b, c)` = `a*b + c` (single VALU slot)
- `vselect(dest, cond, a, b)` = per-lane select (single flow slot)
- `load_offset(dest, addr, offset)` = gather with static offset
- `vload/vstore` = contiguous 8-element vector load/store
- Scratch space: 1536 words (registers + constants + arrays)
- All effects take place at end of cycle (write-after-read within same cycle is safe)

**Scoring:**
- Baseline: **147,734 cycles**
- Submission test: `python tests/submission_tests.py`
- Only final `values` array is checked (not indices)

---

## Current State

| Metric | Value |
|--------|-------|
| **Cycle count** | **1446** |
| **Speedup** | **102.17x** over baseline |
| **Tests passing** | **8/9** |
| **Only failing test** | `test_opus45_improved_harness` (requires < 1363, need 83 more cycles) |

**Current bottlenecks (from diagnostics):**
- `valu`: **92.5%** utilization (near saturation)
- `load`: **91.7%** utilization (near saturation)
- `flow`: saturated **35.4%** of cycles (1 slot/cycle limit)
- `alu`: low utilization (~10-15%), mostly idle
- `store`: low utilization

---

## Optimization History (What Worked)

### Phase 1: Foundation (147,734 → 2,177 cycles) — Tasks 1-16

| Optimization | Cycles | Delta | Key Insight |
|-------------|--------|-------|-------------|
| VLIW scheduler with dependency tracking | 13,391 | -134,343 | Packs independent ops into same cycle |
| SIMD vectorization + gather | 14,415 | (combined) | Process 8 elements at once |
| Multi-group interleaving (8 groups) | 2,660 | -11,755 | Overlaps independent dependency chains |
| Pre-broadcast constants + dedup | 2,636 | -24 | Eliminate redundant const loads |
| DCE optimizer pass | 2,632 | -4 | Remove dead writes |
| **Batch in scratch across rounds** | **2,177** | **-455** | **Biggest single-task win**: load batch once, operate in scratch, store once at end |

### Phase 2: Algorithmic Depth Exploitation (2,177 → 1,486 cycles) — Opts 2-6

| Optimization | Before → After | Delta | Key Insight |
|-------------|---------------|-------|-------------|
| **Depth-aware gather elimination** | 2,123 → 1,764 | **-359** | Depths 0-2 have deterministic node sets (all start at idx=0). Preload nodes 0-6 as constants, select with arithmetic/vselect instead of memory gather. Eliminated 1536 loads. |
| **Interleave group grid search** | 1,764 → 1,566 | -198 | Increased interleave from 8→26 groups. Sweet spot found via grid search. |
| **Depth-1/2 VALU reduction** | 1,563 → 1,547 | -16 | Algebraic rewrites: single `multiply_add` instead of multiple ops for node selection |
| **Flow-branch select + retune** | 1,547 → 1,486 | -61 | Moved `branch = (val&1)+1` from VALU to `flow.vselect`, freeing VALU pressure. Retuned interleave to 25/26 split. |

### Phase 3: Micro-Optimizations (1,486 → 1,446 cycles) — Opts 8-11

| Optimization | Before → After | Delta | Key Insight |
|-------------|---------------|-------|-------------|
| Depth-2 pairwise flow select | 1,486 → 1,478 | -8 | Careful single vselect (not a tree) with explicit dependencies |
| Non-debug index traffic elimination | 1,478 → 1,474 | -4 | Submission only checks values, skip idx loads/stores |
| Compact early-depth index state | 1,474 → 1,453 | -21 | Carry path bits instead of full idx for depths 0-2 |
| Dead-setup pruning + interleave retune | 1,453 → 1,446 | -7 | Remove unused vectors in submission path, raise early interleave to 29 |

---

## What Did NOT Work (Critical Lessons)

### 1. Root Node Caching (Task 17) — REVERTED
- **Attempted:** Cache root node in scratch, conditional blend `if idx==0`
- **Result:** 2,177 → 2,351 cycles (regression)
- **Why:** Extra compare/blend ops added more overhead than the cache saved. Static scratch addressing means you can't index by runtime idx.

### 2. Depth-2 Full Flow Select Tree (Opt 7) — REVERTED
- **Attempted:** Replace entire depth-2 arithmetic with three `flow.vselect` ops
- **Result:** Broke correctness (0/9 tests passing)
- **Why:** Scheduler reordering with overlapping scratch registers creates WAR hazards. Flow-select trees are extremely fragile without explicit dependency anchoring.

### 3. Depth-3 Compact State (Opt 13) — REVERTED
- **Attempted:** Extend compact traversal through depth-3, preload nodes 7-14, 8-way flow.vselect tree
- **Result:** Correctness fixed, but regressed to ~1681 cycles
- **Why:** Three compounding problems:
  1. **Flow pressure explosion** — 8-way select needs many `flow.vselect` ops, but flow has only 1 slot/cycle
  2. **Scratch pressure** — New vectors forced lowering early interleave from 29→26
  3. **Setup overhead** — Node preloads/broadcasts didn't amortize

### 4. Vector Address Precompute (Opt 12) — REVERTED
- **Attempted:** Pre-compute and reuse vector addresses across rounds
- **Result:** Correctness broke (scheduling/dependency hazard)
- **Why:** Address-form rewrites are fragile under VLIW reordering unless dependency anchoring is explicit

### 5. Various Parameter Sweeps (Opt 12) — NO GAIN
- Searched hundreds of scheduler configs (crit_weight, engine_bias, interleave combos)
- **Result:** No config beat 1446
- **Conclusion:** Kernel is at a local optimum for current transformation set

### 6. Micro-optimizations with ~0 Impact
- `multiply_add` for hash stages initially added 1 cycle (setup overhead)
- `*2` → `<<1` replacement: no measurable change
- Scheduler tie-break by slot width: regressed by 1 cycle
- Depth-2 idx materialization VALU→FLOW trade: regressed by 1 cycle

---

## Key Architectural Patterns Discovered

### What reduces cycles
1. **Eliminate memory traffic** — Moving data to scratch, eliminating gathers for deterministic depths
2. **Increase interleave width** — More independent groups = better scheduling freedom
3. **Algebraic simplification** — Fewer ops per element, especially using `multiply_add`
4. **Engine load-balancing** — Move work from saturated engine (VALU) to idle one (flow), but carefully
5. **Dead-work elimination** — Skip idx writes, wrap checks, unused header loads in submission path

### What increases cycles (traps)
1. **Flow-heavy selection trees** — Flow has 1 slot/cycle; any tree structure serializes badly
2. **Scratch pressure** — Forces lower interleave, which reduces scheduling freedom
3. **Register/temp reuse near flow ops** — Causes scheduler WAR hazards and correctness breaks
4. **Conditional blend logic** — Compare + blend adds ops that rarely pay for themselves
5. **Pre-computation that doesn't amortize** — Setup costs for things used rarely

### The fundamental tension
The kernel is **dual-bottlenecked on VALU and load**. Any optimization that reduces one tends to increase the other or increase flow pressure. The only "free" improvements left are:
- Reducing total work (fewer ops per element)
- Better scheduling (unlikely given extensive search)
- Structural changes that reduce both VALU and load simultaneously

---

## Current Kernel Architecture (in perf_takehome.py)

### KernelBuilder Parameters
```python
KernelBuilder(
    emit_debug=False,           # Debug mode (submission=False)
    interleave_groups=25,       # Groups for depth 3+ (gather depths)
    interleave_groups_early=29, # Groups for depths 0-2 (no gathers)
    depth2_select_mode="flow_vselect",  # Depth-2 node selection
    idx_branch_mode="flow_vselect",     # Branch decision mode
    scheduler_crit_weight=1024,         # Scheduler priority weight
)
```

### Kernel Structure
1. **Header** — Load pointers, allocate constants, preload nodes 0-6 into vectors
2. **Body per round** (16 rounds, depth cycles 0→10→0→10→...):
   - **Depth 0:** XOR with preloaded root (vec_node0), hash, store branch bit
   - **Depth 1:** Select node1/node2 via compact path bit, hash
   - **Depth 2:** 4-way select from nodes 3-6 via compact path bits + vselect, hash
   - **Depth 3+:** Memory gather via `load_offset`, hash, full idx update
   - Final depth: skip idx update (dead in submission mode)
3. **Epilogue** — Store values back to memory

### Submission-path optimizations (gated on `not self.emit_debug`)
- Skip loading/storing indices
- Skip n_nodes loading
- Skip wrap checks
- Use compact state for depths 0-2
- Skip idx update at forest_height and final round

---

## Remaining Target

**Need: < 1363 cycles (currently 1446, gap = 83 cycles)**

### Theoretical Lower Bound Analysis
From Opt 3 report: minimum ~1334 cycles based on load requirements alone. This means the gap to theoretical minimum is ~112 cycles. The target of 1363 is only 29 cycles above theoretical minimum.

### Most Promising Unexplored Directions

1. **VALU-centric depth-3 selection (avoid flow)**
   - Use bitwise one-hot/mux arithmetic instead of flow.vselect tree
   - E.g., `result = sum(node_i * (path == i) for i in range(8))` using VALU multiply_add
   - Risk: may still be too many VALU ops, but avoids flow bottleneck
   - Potential: eliminates 8 gather loads per depth-3 iteration

2. **Partial depth-3 optimization**
   - Don't try to eliminate ALL depth-3 gathers
   - Cache only the most frequently hit nodes (statistical approach)
   - Or optimize only half the selection tree

3. **Software pipelining across rounds**
   - Currently rounds are processed sequentially
   - Pipeline: start round N+1 hash while round N's idx update completes
   - Risk: complex dependency management

4. **Algebraic hash simplification**
   - The 6-stage hash dominates cycle count
   - Look for algebraic identities that reduce stages or ops
   - Stage patterns: 3 stages use `op1="+"`, `op2="+"`, `op3="<<"` which already have multiply_add optimization
   - Remaining 3 stages may have similar opportunities

5. **Scratch layout optimization**
   - Reorder scratch allocations to minimize register pressure
   - Phase-split allocations (reuse scratch between non-overlapping phases)

6. **Different interleave strategy per depth**
   - Currently: 29 groups for depths 0-2, 25 groups for 3+
   - Could try different widths for each specific depth

### Known Dead Ends (Don't Retry)
- Full flow.vselect trees for depth-2 or depth-3 selection
- Address precompute/reuse across rounds
- Root node caching with conditional blend
- Interleave groups >= 30 (scratch overflow/correctness issues)
- Pure parameter sweeps (exhaustively searched, local optimum confirmed)

---

## How to Validate Changes

```bash
# Quick correctness + cycle count
python perf_takehome.py Tests.test_kernel_cycles

# Full submission validation (correctness over 8 random seeds + speed thresholds)
python tests/submission_tests.py

# Debug trace (requires emit_debug=True, view in Perfetto)
python perf_takehome.py Tests.test_kernel_trace

# Diagnostics with schedule analysis
python perf_takehome.py Tests.test_kernel_cycles  # with diagnostics_out set
```

**Critical:** Always run `python tests/submission_tests.py` before considering any change a win. The correctness test runs 8 random seeds.

---

## File Map

| File | Purpose |
|------|---------|
| `perf_takehome.py` | **THE kernel to optimize** (KernelBuilder.build_kernel) |
| `problem.py` | Machine simulator, ISA definition, reference kernel |
| `tests/submission_tests.py` | Official submission tests (frozen simulator) |
| `tests/frozen_problem.py` | Frozen copy of simulator for scoring |

---

*Last updated: 2026-02-10 | Current best: 1446 cycles | Target: < 1363 cycles*
