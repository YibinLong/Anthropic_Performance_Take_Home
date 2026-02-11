# Optimization Session Handoff: 1407 → 1382 Cycles

> **For the next agent**: Read this FIRST. It captures everything learned from a multi-agent session that moved the cycle count from 1407 to 1382. The target is < 1363 (19 cycles remain).

## What Actually Worked (and WHY)

### 1. Header flow.add_imm → load.const (-14 cycles)

**The change**: In `header_scratch_const()` and the init_vars loading section, replaced all `flow.add_imm(addr, zero_base, val)` with `load.const(addr, val)`.

**Why it worked**: The header had ~22 `flow.add_imm` ops for loading scalar constants. Flow has only 1 slot/cycle. Load has 2 slots/cycle. Switching to load.const allowed the header to complete in ~16 cycles instead of ~38, because:
- Flow was the bottleneck (22 flow ops = 22 cycles minimum)
- Load could process 2 const loads per cycle (22 ops = 11 cycles)
- The remaining header work (node loads, broadcasts) overlapped with loads

This eliminated **31 zero-VALU cycles** in the header. Those were pure waste - 31 cycles where 6 VALU slots sat empty because there was no VALU work available yet (body ops depended on header outputs).

**Key insight**: The flow engine is a 1-slot-per-cycle bottleneck. ANY work that can move OFF flow is a win, even if the alternative engine (load) is also busy later. Header ops run at the START of the schedule where load is idle.

**Code locations**: `perf_takehome.py` lines ~998-1015 (header_scratch_const and init_vars)

### 2. Prologue/Epilogue flow.add_imm → ALU incremental (-7 cycles)

**The change**: For loading initial values and storing final values, replaced `flow.add_imm(tmp_addr_b, inp_values_p, offset)` with ALU incremental addressing:
```python
if base == 0:
    body.append(("alu", ("+", tmp_addr_b, self.scratch["inp_values_p"], zero_const)))
else:
    body.append(("alu", ("+", tmp_addr_b, tmp_addr_b, vlen_const)))
```

**Why it worked**: Eliminated 64 `flow.add_imm` ops (32 prologue + 32 epilogue). ALU has 12 slots/cycle and was at 0% utilization. The 64 ALU ops are essentially "free" - they fill otherwise-empty ALU slots.

**The trade-off**: The ALU incremental approach creates a SERIAL dependency chain (each `tmp_addr_b += 8` depends on the previous). This means addresses are computed one-at-a-time, not in parallel. But each ALU op can overlap with the vload/vstore that uses the PREVIOUS address (same cycle: vload reads old tmp_addr_b, ALU writes new tmp_addr_b; effects at end of cycle).

**Code locations**: ~lines 1589-1604 (prologue) and ~1685-1694 (epilogue)

### 3. Scheduler Retuning (-4 cycles)

**The change**: `scheduler_crit_weight=220, scheduler_succ_weight=5120, scheduler_random_seed=202`

**Why it worked**: The structural changes (header + prologue) altered the dependency DAG shape. The previous optimal weights (crit=136, succ=3584, seed=51) were tuned for the old DAG. The new DAG has different dependency patterns (fewer flow ops, different header structure), so different weights produce better schedules.

**Critical lesson**: ALWAYS retune scheduler parameters after any structural change. The weights are coupled to the DAG shape.

## Pitfalls and Mistakes

### 1. Session Corruption / Stale State

**What happened**: Early in the session, I ran analysis scripts that imported `perf_takehome` and got wildly wrong results (1651 instructions, 2982 ALU ops). I spent significant time debugging this phantom issue.

**Root cause**: Python process state was corrupted - either stale imports, module caching, or the working directory wasn't set correctly. Running `from perf_takehome import KernelBuilder` in a fresh `python3 -c "..."` subprocess always gave correct results.

**Lesson for future agents**:
- ALWAYS use fresh `python3 -c "..."` subprocesses for testing, never rely on persistent Python sessions
- If numbers don't match expectations, restart from scratch before investigating
- The `do_kernel_test()` function uses the SAME `mem` for both machine and reference (Machine copies it internally), so it works. Direct Machine() construction needs explicit `copy.copy(mem)` for the reference.

### 2. The "Correct" Critical Path Fix That Made Things Worse

**What happened**: The scheduler researcher found that the critical path computation treats weak (WAR) dependencies with the same 1-cycle latency as strict (RAW) dependencies. Mathematically, weak deps should have 0 latency (same-cycle scheduling is OK).

**What I did**: "Fixed" the critical path to use 0 latency for weak edges.

**Result**: Cycles went from 1382 to 1427 (45-cycle REGRESSION). Even after retuning weights, best was 1397.

**Why**: The "bug" was actually a feature. The inflated critical path values for ops reachable through weak edges gave them HIGHER priority, which happened to produce better scheduling decisions for this specific kernel. The scheduler weights were co-optimized with the "buggy" critical path.

**Lesson**: Not every mathematically "correct" change improves performance. Heuristic schedulers develop symbiotic relationships between their components. Changing one component (critical path) requires retuning all others (weights), and the new optimum may be worse than the old one.

### 3. The 4-Way Parallel Prologue Disaster

**What happened**: I tried to use 4 temp address registers (instead of 1) for parallel prologue address computation, reducing the serial dependency chain.

**Result**: Correctness broke AND cycles increased (1495).

**Why**: I included `tmp_addr` (shared with idx loading path) as one of the 4 prologue temps. Even though the idx path is disabled in submission mode, the code structure and dependency tracking still interacted badly. The parallel approach also needed extra `flow.add_imm` ops for initialization (4 initial addresses), partially negating the benefit.

**Lesson**: Reusing scratch registers across different code paths is fragile. Each register should have ONE clear owner. If you need parallelism, allocate DEDICATED registers.

### 4. Massive Parameter Sweeps That Found Nothing

**What happened**: I ran sweeps of 1000+ seeds, 350+ weight combinations, beam widths 1-5, multi-start with 100 seeds. Total: thousands of scheduler configurations.

**Result**: ALL gave >= 1382 cycles.

**Lesson**: Once you've found the best parameters for a given DAG structure, MORE parameter sweeping won't help. The schedule is a LOCAL OPTIMUM. You need STRUCTURAL changes to the DAG (different ops, different dependencies) to unlock new scheduling possibilities. Parameter sweeps are only useful AFTER structural changes.

### 5. Depth-3 Deterministic Select: Promising Theory, Fatal Practice

**What happened**: Preloading depth-3 nodes (7-14) and using compare+select instead of memory gathers. Theory: eliminates 512 load_offset ops per depth-3 round.

**Result**: Various attempts all regressed (1612+).

**Why**: The 8-way select needs either:
- 7 flow.vselect ops (flow = 1/cycle = 7 cycles per group per round) → flow pressure explosion
- VALU arithmetic select (~17 VALU ops per group) → VALU pressure explosion
- Either way, the load savings don't offset the new bottleneck

**Lesson**: When VALU is at 94%+ utilization and flow is at 24%, you CANNOT move work TO either VALU or flow. The only "free" engine is ALU (12 slots, 0% utilized), but ALU can only do scalar ops (1 element at a time vs VALU's 8).

## The State of the Kernel at 1382 Cycles

### Engine Utilization
| Engine | Slots/cycle | Total ops | Utilization |
|--------|------------|-----------|-------------|
| VALU | 6 | 7,967 | 96.1% |
| Load | 2 | 2,623 | 94.8% |
| Flow | 1 | 256 | 18.5% |
| ALU | 12 | 70 | 0.4% |
| Store | 2 | 32 | 1.2% |

### VALU Waste Distribution (1382 cycles)
- VALU=6/6: 1,248 cycles (90.3%) - no waste
- VALU=5/6: 49 cycles - 49 wasted slots
- VALU=4/6: 36 cycles - 72 wasted slots
- VALU=3/6: 20 cycles - 60 wasted slots
- VALU=2/6: 8 cycles - 32 wasted slots
- VALU=1/6: 14 cycles - 70 wasted slots
- VALU=0/6: 7 cycles - 42 wasted slots
- **Total wasted: 325 VALU slots** (need ≤ 211 for target)

### Where the Waste Lives
1. **Header** (cycles 0-7): 42 wasted slots - initial loads before VALU work is available
2. **Mid-schedule gaps** (cycles ~590-654, ~985-989): ~164 wasted slots - round transition stalls where groups synchronize
3. **Tail** (cycles 1373-1381): ~37 wasted slots - epilogue stores winding down
4. **Scattered**: ~82 wasted slots across 85 partially-utilized cycles

### Theoretical Lower Bound
- **VALU minimum: 1,328 cycles** (7,967 / 6)
- **Load minimum: 1,312 cycles** (2,623 / 2)
- **Current: 1,382 cycles** (54 above VALU minimum = 96.1% efficiency)
- **Target: < 1,363** (35 above minimum = 97.4% efficiency needed)

## Key Mathematical Facts

1. **7,967 VALU ops** are essentially minimal for this algorithm
2. **12 VALU ops per hash** is irreducible (3 multiply_add + 3 × 3 three-op stages)
3. **Hash serial depth: 9 cycles** (multiply_add=1 cycle, three-op=2 cycles each)
4. **256 flow.vselect ops** for depth 1-2 node selection are necessary
5. **2,560 load_offset ops** for gather rounds are necessary
6. To reach 1363: need VALU efficiency of 97.4% (currently 96.1%)
7. This means eliminating 114 of 325 wasted VALU slots

## File Map
| File | Purpose |
|------|---------|
| `perf_takehome.py` | THE kernel to optimize (KernelBuilder.build_kernel) |
| `problem.py` | Machine simulator, ISA definition, reference kernel |
| `tests/submission_tests.py` | Official submission tests (DO NOT MODIFY) |
| `tests/frozen_problem.py` | Frozen simulator for scoring |

## Validation Commands
```bash
# Must be empty:
git diff origin/main tests/

# Must show CYCLES: 1382, 8/9 tests passing:
python tests/submission_tests.py
```

*Session date: 2026-02-10/11 | Starting point: 1407 cycles | Final: 1382 cycles | Target: < 1363*
