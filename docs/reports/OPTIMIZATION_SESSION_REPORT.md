# Optimization Session Report: perf_takehome.py

## Summary

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Cycle count | 2177 | 2123 | -54 (-2.5%) |
| Speedup over baseline | 67.9x | 69.6x | +1.7x |
| Load utilization | 96.8% | 99.1% | +2.3% |
| Zero-load cycles | 60 | 16 | -44 |
| Single-load cycles | 31 | 1 | -30 |
| Tests passing | 3/9 | 4/9 | +1 |

New test passed: `test_opus4_many_hours` (< 2164 cycles).

---

## Architecture Context

The target is a custom VLIW processor with per-cycle slot limits:

| Engine | Slots/cycle | Role |
|--------|-------------|------|
| ALU | 12 | Scalar integer ops |
| VALU | 6 | Vector ops (VLEN=8) |
| Load | 2 | Memory reads + scratch constants |
| Store | 2 | Memory writes |
| Flow | 1 | Branches, select, pause |

The kernel performs a parallel tree traversal: 256 batch elements × 16 rounds × 1 gather + hash per element. The dominant cost is 4096 gather loads (8 `load_offset` per vector group × 32 groups × 16 rounds).

---

## Optimizations Applied

### 1. Pause Removal (-2 cycles)

**What:** The kernel emitted two `flow.pause` instructions (lines 541, 726). The submission harness sets `enable_pause=False`, making them no-ops that still consume 1 cycle each (pause is a VLIW barrier).

**Change:** Wrapped both in `if self.emit_debug:`.

**Lesson for future agents:** The submission test (`tests/submission_tests.py`) and the local trace test (`do_kernel_test` in `perf_takehome.py`) have different requirements. The submission test disables pauses and debug entirely. The local trace test requires pauses to match `reference_kernel2`'s yield points. Always check BOTH test paths when modifying control flow. The `emit_debug` flag is the correct gate for pause emission — debug mode needs pauses, submission mode doesn't.

### 2. Offset Const Loads into VLIW Body (-16 cycles)

**What:** The prelude loaded 32 offset constants (0, 8, 16, ..., 248) via `self.scratch_const()`, which calls `self.add()` and emits directly to `self.instrs` — bypassing VLIW scheduling. Each took a full cycle with only 1 of 2 load slots used.

**Change:** Pre-allocated scratch addresses for all offsets, emitted `("load", ("const", addr, val))` into `body[]` instead, and referenced the same addresses in the epilogue without re-emitting loads.

**Key implementation detail:** The epilogue must NOT re-emit const loads — the values persist in scratch from the prelude. Just reference the same `offset_addrs[base]`.

**Lesson for future agents:** Any operation emitted via `self.add()` goes to `self.instrs` as a single-instruction bundle, completely outside VLIW scheduling. This is a major source of waste. Always check whether operations can be moved into the `body[]` list for VLIW scheduling. The pattern to watch for: `self.scratch_const()` → `self.add("load", ...)` → single-load cycle.

### 3. Multiple tmp_addr Registers (-3 cycles)

**What:** The prelude and epilogue used a single `tmp_addr` register for ALL address computations, creating WAW (write-after-write) dependencies that serialized them.

**Change:** Added `tmp_addr_b` and used it for val-array addresses, while `tmp_addr` handles idx-array addresses. Also reordered operations so both ALU computations precede both loads/stores, enabling the scheduler to issue them in parallel.

**Lesson for future agents:** WAW dependencies are "weak" in the scheduler (same-cycle or later, not strictly +1 cycle), but they still constrain scheduling. When you see the same scratch register written by consecutive independent operations, allocate separate registers. The cost is 1 scratch word per extra register — negligible compared to the cycle savings.

### 4. Header VLIW Scheduling (-30 cycles)

**What:** The header setup (const loads for header indices, memory loads for pointers, scalar const loads for hash constants, vbroadcast operations) was emitted entirely via `self.add()` — 41 single-instruction cycles.

**Change:** Collected all header operations into a `header[]` list and merged them into `body[]` for joint VLIW scheduling (in non-debug mode). In debug mode, the header is scheduled separately before the pause barrier.

**Critical gotcha — DCE kills isolated headers:** Initially I tried scheduling the header as a separate VLIW segment (`self.build(header, vliw=True)`). This produced 0 cycles because the `_optimize_slots` DCE pass removed all header ops — they write to scratch but nothing *within the same segment* reads them for a side effect. The body (a separate segment) reads them, but DCE doesn't see cross-segment liveness. The fix was merging header into body so DCE sees the full data flow.

**Secondary gotcha — separate header tmp registers:** The original code used a single `tmp1` register for all 4 header loads (`("const", tmp1, idx); ("load", dest, tmp1)`). With VLIW scheduling, the 4 pairs would serialize on `tmp1`. I allocated 4 separate `header_tmp_addrs` to break this chain.

**Lesson for future agents:** This was the single largest optimization (30 cycles). The general principle: any code emitted via `self.add()` should be moved into a VLIW-scheduled list if possible. The DCE pitfall is critical — always merge related segments rather than scheduling them separately, unless a barrier (pause, jump) naturally separates them.

### 5. Hash Algebraic Simplification (-3 cycles)

**What:** Hash stages 0, 2, 4 follow the pattern: `tmp = a + const; result = multiply_add(a, (1<<shift), tmp)` = 2 VALU ops. Algebraically: `a*(1<<shift) + (a + const) = a*((1<<shift)+1) + const` = 1 `multiply_add` op.

**Change:** Added combined multiplier vector constants (4097, 33, 9) in the header, and emitted single `multiply_add(val, val, combined_mul_vec, const_vec)` for qualifying stages.

**Important context:** This optimization was TRIED FIRST without the header merge and made things 1 cycle WORSE. Only after optimization #4 (header VLIW scheduling) did it help. The reason: with the header merged, reducing VALU pressure shortens the pipeline drain at the end of the kernel (16 → 13 zero-load cycles at the tail). Without the merge, the scheduling change had a net negative effect.

**Lesson for future agents:** Optimizations interact. Reducing VALU ops doesn't help when loads are the bottleneck — UNLESS it affects the pipeline drain at the end. Always test optimizations in combination, not just isolation.

### 6. Critical-Path Scheduler Priority (0 cycles)

**What:** The VLIW scheduler used instruction index as heap priority. Changed to `(-critical_path_length, index)` so operations on the critical path are scheduled first.

**Change:** Added backward pass to compute longest path from each op to any terminal, used as primary sort key in the ready heap.

**Result:** No cycle improvement. The scheduler was already achieving near-optimal packing because the load engine is saturated at 99.1%.

**Lesson for future agents:** When one engine is the clear bottleneck (>97% utilization), scheduler heuristic changes have minimal impact. The scheduler's job is to fill idle slots on non-bottleneck engines, and when the bottleneck is near-saturated, the schedule is essentially forced. Save scheduler work for situations with more slack.

---

## What Didn't Help

| Attempt | Result | Why |
|---------|--------|-----|
| Different interleave groups (4-32) | 0 cycles (4 was worse) | Load bottleneck forces the schedule regardless of group count |
| Hash simplification without merged header | +1 cycle (worse) | Fewer VALU ops changed scheduling slightly for the worse |
| Splitting pair+combine VALU ops | 0 cycles | Scheduler already packs them optimally |
| Critical-path scheduling | 0 cycles | 99.1% load utilization leaves no room for scheduling improvement |
| Cross-round interleaving analysis | N/A (not needed) | Scheduler already achieves 0 zero-load cycles between rounds |

---

## Current Bottleneck Analysis

```
Load utilization:  99.1% (2 loads/cycle, 4214 total loads over 2123 cycles)
VALU utilization:  88.5%
ALU utilization:    0.5%
Store utilization:  1.5%
Flow utilization:   0.0%
```

The kernel is **load-bound**. Every cycle except the final 16 uses both load slots. The 16 trailing zero-load cycles are pipeline drain for the last round's hash chain and epilogue stores.

### Cycle Breakdown

| Phase | Cycles | Description |
|-------|--------|-------------|
| Header + prelude + main loop | 2107 | 2 loads/cycle, fully saturated |
| Pipeline drain (tail) | 16 | VALU hash completion + stores, no loads |
| **Total** | **2123** | |

### Theoretical Minimum

| Load source | Count | Cycles at 2/cycle |
|-------------|-------|--------------------|
| Gather `load_offset` | 4096 | 2048 |
| Prelude `vload` | 64 | 32 |
| Offset `const` | 32 | 16 |
| Header `const` + `load` | ~20 | ~10 |
| **Total** | **~4212** | **~2106** |

Current overhead above theoretical: 2123 - 2106 = **17 cycles** (pipeline drain + 1 unpaired load at the end).

---

## Guidance for Further Optimization (Toward < 1790)

### The Fundamental Problem

The < 1790 target is BELOW the 2048-cycle minimum for 4096 gather loads at 2 loads/cycle. This means **the number of gather loads must be reduced**. No amount of scheduling improvement can bridge this gap.

### Promising Directions

**1. Tree caching in scratch memory**

The tree has 1023 nodes. Scratch has 691 free words. Can't fit the full tree, but can cache the upper 9 levels (511 nodes).

After each element wraps to root (idx=0), it traverses the same upper levels deterministically. With 256 batch elements and 16 rounds, upper-level nodes are accessed thousands of times. Caching levels 0-8 in scratch and reading from scratch instead of memory would eliminate most gather loads for rounds 11-16 (after first wrap-around).

**Implementation challenges:**
- Need to preload 511 tree values from memory into scratch (256 additional prelude loads)
- Need conditional logic: if `idx < 512`, read from scratch; else, gather from memory
- `vselect` (flow engine, 1/cycle) would be too slow for the condition
- Could use arithmetic trick: `scratch_val * (idx < 512) + gather_val * (idx >= 512)` using VALU, but requires both values to be loaded first
- May need to split batch into "cached" and "uncached" subsets per round

**Scratch budget:** Would need to reduce batch arrays. Processing batch in 2 chunks of 128 (128 fewer idx + val words = 256 freed) plus 511 tree cache = 757 words needed, 691 available — still short by 66. Could reduce interleave groups or share temp registers to free more scratch.

**2. Batch chunking with runtime loop**

Process the batch in 2 halves (128 each) using `cond_jump` for the outer loop. Each half uses 128-word idx/val arrays, freeing 256 scratch words for tree caching.

**Cost:** Loop overhead (~2 cycles per iteration × 16 rounds × 2 halves = 64 cycles) plus pipeline drain per loop iteration (~16 × 32 = 512 cycles). This is much worse unless tree caching saves >500 gather loads.

**3. Store/reload between rounds**

Use the store engine (1.5% utilized, 2 slots/cycle) to write idx/val to memory after each round and reload from memory for the next round. This frees ALL 512 batch scratch words for tree caching. But adds 128 loads + 128 stores per round = 2048 extra loads + 2048 stores over 16 rounds. The store engine has capacity, but loads would double. Only viable if tree caching saves more loads than the store/reload adds.

**4. Algorithmic insight: wrap-around optimization**

After round 10, all batch elements wrap to idx=0 (root). For rounds 11-16, they all traverse the same upper tree path. The node values they encounter are deterministic based only on their hash value. This could enable precomputation or lookup-table approaches for the wrapped portion.

**5. Reduction in hash VALU pressure to improve pipeline drain**

The current 16-cycle pipeline drain at the end is VALU-limited (hash chain tail). Further reducing the hash chain (already 9 ops from original 12) could shave 1-3 more cycles. Diminishing returns — max 3 cycles.

### What NOT to Try

- **More interleave groups:** Already tested 4-32, no effect
- **Scheduler heuristic tuning:** Load utilization is 99.1%, scheduler can't help
- **Loop for round iteration:** Creates 16 pipeline drains instead of 1
- **Scalar processing:** Same load count as vector, worse VALU utilization
- **Flow engine for computation:** Only 1 slot/cycle, bottleneck

### Key Numbers to Remember

- 4096 gather loads = immutable floor of 2048 cycles at 2 loads/cycle
- 1790 target < 2048 → **must eliminate gathers**
- 691 free scratch words < 1023 tree nodes → **can't cache full tree**
- 512 batch words reclaimable via chunking → 691 + 256 = 947 available
- Upper 9 tree levels = 511 nodes → fits in 947 with chunking

---

## File Reference

All changes are in `perf_takehome.py`:

| Section | Lines | Description |
|---------|-------|-------------|
| `_schedule_vliw()` | ~249-380 | VLIW scheduler with critical-path priority |
| `build_hash_vec()` | ~452-500 | Hash with algebraic simplification |
| `build_kernel()` header | ~494-580 | Header ops collected into list for VLIW |
| `build_kernel()` prelude | ~660-690 | Offset consts in body, dual tmp_addr |
| `build_kernel()` epilogue | ~720-755 | Dual tmp_addr for stores |
| Pause gates | ~556, ~757 | Conditional on `self.emit_debug` |
