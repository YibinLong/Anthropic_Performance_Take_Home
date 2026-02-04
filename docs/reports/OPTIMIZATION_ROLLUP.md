# Optimization Rollup (Cycle Reduction Worklog)

This document consolidates what was implemented (and what was tried/reverted) while working through:

- `docs/improvements/IMPROVEMENTS_A.md`
- `docs/improvements/IMPROVEMENTS_B.md`
- `docs/improvements/IMPROVEMENTS_C.md`
- `docs/reports/task*_report.md`

Primary implementation target: `perf_takehome.py` (especially `KernelBuilder.build_kernel()`).

The goal of this rollup is to give a future agentic LLM an accurate, high-signal picture of what has already been done to reduce simulated cycles, including key pitfalls and the current kernel shape.

## Current Status (Verified)

As of 2026-02-04, verified locally via:

```bash
python tests/submission_tests.py
```

- Current cycle count: **2177**
- Baseline cycle count: **147,734**
- Speedup: **~67.86x**
- Tests passing:
  - Correctness (`test_kernel_correctness`)
  - Speed thresholds: `< 147,734` and `< 18,532`
- Tests failing (speed only):
  - `< 2,164` (missed by **13** cycles)
  - `< 1,790`, `< 1,579`, `< 1,548`, `< 1,487`, `< 1,363`

## Architectural Facts That Drove Most Design Choices

These are the key constraints from `problem.py` / `tests/frozen_problem.py` and summarized in `docs/improvements/IMPROVEMENTS_C.md`:

- One instruction bundle per cycle; per-engine slot limits:
  - `alu` 12, `valu` 6, `load` 2, `store` 2, `flow` 1
- Scratch operands are **static addresses** in the program; no indirect scratch addressing at runtime.
- Writes commit at **end of cycle**:
  - RAW and WAW must be scheduled in later cycles.
  - WAR is safe in the same cycle (reads see old values), but a write must not be scheduled *before* the last read.
- `vload`/`vstore` are only for **contiguous** memory regions; gathers require `load_offset`.
- Cycle counting: instruction bundles count as cycles if they contain any non-`debug` engine slots; bundles containing only `debug` slots do **not** count as cycles.

## What The Kernel Looks Like Now (High-Level)

The kernel in `perf_takehome.py` is an optimized, scheduled, SIMD implementation with scratch-resident idx/val:

1. **Header loads** (explicit header indices):
   - Loads only: `n_nodes`, `forest_values_p`, `inp_indices_p`, `inp_values_p`.
2. **Constant setup**:
   - Scalar constants are deduped via `scratch_const()`.
   - Vector constants are deduped via `vec_const_map` + `alloc_vec_const()` (including hash constants and hash `multiply_add` multipliers).
   - `vec_n_nodes` and `vec_forest_base` are broadcast from header-loaded scalars.
3. **Scratch-resident batch arrays (Task 16)**:
   - Allocate `idx_arr[batch_size]` and `val_arr[batch_size]` in scratch.
   - **Prelude**: load full batch from memory to scratch once (`vload` for vector part; scalar loads for tail).
4. **Main loop**:
   - Compile-time loop: `for round in range(rounds)` in Python emits unrolled machine code (no runtime `cond_jump` loops).
   - SIMD vector path processes `VLEN=8` elements at a time.
   - **Multi-group interleaving (Task 3)**: `interleave_groups = 8` with per-group scratch registers for the gather path:
     - `vec_addr_g*` and `vec_node_val_g*` per group.
     - These per-group regs are also reused as hash temporaries (`vec_tmp1 = vec_addr`, `vec_tmp2 = vec_node_val`).
   - Gather: compute `addr_vec = forest_values_p + idx_vec` then issue 8x `load_offset`.
   - Hash: `val ^= node_val`, then `build_hash_vec()` applies the 6-stage hash in SIMD.
   - Index update (flow-select removed):
     - `branch = (val & 1) + 1`
     - `idx = idx*2 + branch` (vector uses `valu.multiply_add`)
     - wrap: `idx = idx * (idx < n_nodes)`
   - Scalar tail path handles elements beyond `vec_count` (for general batch sizes).
5. **Epilogue**:
   - Store scratch-resident `idx_arr` and `val_arr` back to memory once (`vstore` for vector part; scalar stores for tail).
6. **Scheduling**:
   - The entire `body` slot list is passed through dead-code elimination and then scheduled into packed bundles via the custom VLIW scheduler.

## Implemented Optimizations (By Improvement/Task)

Below is what was implemented, as captured by `docs/improvements/IMPROVEMENTS_C.md` and the per-task reports.

### Task 1: Real VLIW scheduler / slot packer

Files: `perf_takehome.py`

Key implementation details:

- Implemented `KernelBuilder._schedule_vliw()`:
  - Builds an IR-like list from `(engine, slot)` pairs.
  - Computes per-op `reads`/`writes` using `_slot_reads_writes()`.
  - Builds dependencies using two edge types:
    - **Strict deps**: RAW + WAW; successor must be in a *later* cycle.
    - **Weak deps**: WAR; successor can be in the *same* cycle.
  - Schedules greedily, cycle-by-cycle, respecting `SLOT_LIMITS` per engine.
- Implemented barrier handling (`_is_barrier()`):
  - Flow ops like `pause`, `halt`, `jump`, `cond_jump*` break scheduling segments and are not reordered across.
- Added `emit_debug` flag to `KernelBuilder` to omit debug slots in submission builds.

Measured result (Task 1 report, scheduler only): **13,391 cycles** (correctness passed).

### Task 2: SIMD vectorization + gather via `load_offset`

Files: `perf_takehome.py`

Key implementation details:

- Added SIMD hash builder `build_hash_vec()` using `valu`.
- Vector loop structure:
  - `vload`/`vstore` for contiguous idx/val.
  - Gather via:
    - `valu("+", addr_vec, forest_base_vec, idx_vec)`
    - 8x `load_offset(node_val_vec, addr_vec, offset)`
  - Vector parity/wrap logic originally used `vselect` (later removed in Task 5).
- Scalar tail loop for non-multiple-of-`VLEN`.

Measured result (Task 2 report, SIMD only): **14,415 cycles** (correctness passed).

### Task 3: Software pipelining / multi-group interleaving

Files: `perf_takehome.py`

Key implementation details:

- Introduced `interleave_groups = 8`.
- Allocated per-group independent scratch regs so the scheduler can overlap groups:
  - Separate `vec_addr` / `vec_node_val` registers per group.
- Reworked vector loop to process `VLEN * interleave_groups` at a time and emit per-group ops via a helper.

Measured result (Task 3 report, in the then-current codebase): **~2660 cycles**.
Quick sweep recorded in the report:
- 4 groups: ~3425 cycles
- 8 groups: ~2660 cycles (best)
- 16 groups: no further improvement

### Task 4: Hash stage pair/combine parallelism

Files: `perf_takehome.py`

Key implementation details:

- Hash stage structure changed to:
  - cycle A: pair ops `(op1)` and `(op3)` (independent) emitted as a grouped slot-list
  - cycle B: combine op `(op2)` emitted separately
- Scheduler extended to treat grouped same-engine slot-lists as atomic units that consume multiple slots in a single cycle (via `slot_count` and unioned read/write sets).

Measured result (Task 4 report): no cycle change observed at that stage (still ~2660), but pairing was made explicit/robust.

### Task 5: Eliminate flow selects with arithmetic (parity + wrap)

Files: `perf_takehome.py`

Key implementation details:

- Replaced `% 2`, `== 0`, and `select/vselect` with arithmetic:
  - `branch = (val & 1) + 1`
  - `idx = 2*idx + branch`
  - `idx = idx * (idx < n_nodes)` for wrap
- Applied to both vector path and scalar tail path.

Measured result (Task 5 report): no cycle change observed at that stage (still ~2660).

### Task 6: Pre-broadcast and reuse constants

Files: `perf_takehome.py`

Key implementation details:

- Added `scratch_const(val)` to dedupe scalar constants (`load const` only once per unique immediate).
- Added `vec_const_map` and `alloc_vec_const(val)` to dedupe vector broadcasts (`vbroadcast` only once per constant).
- Pre-allocated `vec_one`, `vec_two`, and all hash stage constants before the hot loop.

Measured result (Task 6 report, combined with other work already present): **2636 cycles** (correctness passed).

### Task 7: Running pointers for input arrays (historical; no longer present in current code)

Files: `perf_takehome.py`

Key implementation details from the report (this was present in earlier iterations):

- Advanced per-group running index pointers with `flow.add_imm`.
- Removed per-iteration flow update for values pointers; derived `val_ptr` from `idx_ptr_next + batch_size` via ALU to reduce flow-slot pressure.
- Similar pattern for scalar tail.

NOTE: The current code no longer contains `idx_ptr`/`val_ptr` logic; this was superseded by the Task 16 rewrite that loads the full batch into scratch once.

### Task 8: Loop structure decision (looped vs unrolled)

Files: `perf_takehome.py`

What was verified/used:

- Compile-time Python loops (`for round in range(rounds)` plus nested vector chunk loops) generate unrolled machine code.
- The simulator supports runtime loops via `cond_jump`/`cond_jump_rel`, but the current kernel does not use runtime jumps for looping.

Measured result at the time of the report: **2636 cycles** (reflecting the then-cumulative state).

### Task 9: Remove pause/debug in submission path (partially implemented)

Files: `perf_takehome.py`

What exists:

- `emit_debug` flag causes debug-engine slots to be omitted from scheduled code paths (`KernelBuilder.add()` skips debug slots, and `KernelBuilder.build()` filters them).

Important nuance (relevant for future work):

- `pause` is a **flow** instruction, so it is not covered by `emit_debug` filtering.
- The kernel currently emits two `flow.pause` instructions to match `reference_kernel2()` yields for local debugging. Those pause bundles still count as cycles in submission runs because they are non-debug bundles (even when `Machine.enable_pause=False`).

### Task 10: Use `valu.multiply_add` for applicable hash stages

Files: `perf_takehome.py`

Key implementation details:

- In `build_hash_vec()`, for stages with pattern `(a OP1 const1) + (a << shift)`:
  - `tmp1 = op1(a, const1)`
  - `a = multiply_add(a, (1<<shift), tmp1)`
- Precomputed vector multipliers `(1 << shift)` once and cached them in `vec_const_map` (computed as `vec_one << shift_vec`).

Measured result at the time (Task 10 report): **2637 cycles** (a slight regression vs 2636 then, attributed to pre-loop multiplier setup).

### Task 11/12: Slot utilization diagnostics

Files: `perf_takehome.py`

Key implementation details:

- Added `analyze_utilization`, `format_utilization`, `print_utilization`.
- Designed to match simulator cycle accounting: bundles containing only `debug` slots are ignored.
- Wired into `do_kernel_test(..., utilization=True)` for printing.

Measured result at the time: no cycle change (still **2637** in those reports).

### Task 13: Eliminate unused header loads

Files: `perf_takehome.py`, `docs/improvements/IMPROVEMENTS_C.md`

Key implementation details:

- Removed loads/allocations for unused headers: `rounds`, `batch_size`, `forest_height`.
- Fixed a real correctness bug encountered during removal:
  - Header indices are fixed by `build_mem_image()`; removing list entries shifted indices and initially caused out-of-range access in gather.
  - Fix: load headers using explicit `(name, header_index)` pairs:
    - `n_nodes=1`, `forest_values_p=4`, `inp_indices_p=5`, `inp_values_p=6`.
- Introduced a build-time `batch_size_const` where needed (in earlier code shape).

Measured result (Task 13 report): **2632 cycles**.

### Task 14: Small arithmetic simplifications

Files: `perf_takehome.py`

Key implementation details:

- Replaced `* 2` with `<< 1` in:
  - vector idx update (at that time)
  - scalar tail idx update

Measured result (Task 14 report): no cycle change (**2632**).

### Task 15: IR optimizer pass (dead-code elimination)

Files: `perf_takehome.py`

Key implementation details:

- Added `_slot_side_effect()` and `_optimize_slots()`:
  - Backward pass tracking live scratch writes.
  - Keeps flow/store always; keeps debug only when `emit_debug=True`.
  - Drops ALU/VALU/LOAD ops whose outputs are not live and have no side effects.
- Integrated into `KernelBuilder.build()` so each segment is DCE'd before scheduling.

Measured result (Task 15 report): no cycle change (**2632**).

### Task 16: Keep full batch in scratch across rounds (major win)

Files: `perf_takehome.py`

Key implementation details:

- Allocated `idx_arr[batch_size]` and `val_arr[batch_size]` in scratch.
- Added:
  - **Prelude** to load full batch from memory to scratch once.
  - Round body operates on scratch arrays directly (no per-round memory vload/vstore of idx/val).
  - **Epilogue** to store final scratch arrays back to memory once.
- Correctness issue encountered and fixed (per Task 16 report):
  - After moving idx/val to scratch across rounds, the scheduler hoisted `idx <<= 1` earlier than intended and gather used already-shifted indices (out of range).
  - Fix used in current code: replace separate shift+add with a single op:
    - `idx = multiply_add(idx, vec_two, branch)`
    - This ties idx update to `branch` (which depends on the hashed value), preventing the problematic hoist.

Measured result (Task 16 report and current verified): **2177 cycles**.

### Task 17: Cache top tree levels in scratch (regressed) + Task 17B rollback

Files: `perf_takehome.py`

What was tried (Task 17 report):

- Implemented a scratch cache for the root node only (`idx == 0`) due to static scratch addressing constraints.
- Added compare + arithmetic blend (no flow selects) in vector and scalar paths to use cached root when applicable.

Measured result: **2351 cycles** (regression vs 2177).

Rollback (Task 17B report):

- Removed the cache value, broadcasts, blend ops, and extra per-group temps.
- Restored the Task 16 performance level.

Current state: Task 17 cache is **not** present; cycles restored to **2177**.

## Performance Timeline (Reported)

These are the cycle counts recorded in the task reports (note: some tasks were measured in isolation; others were measured against a codebase that already included previous optimizations).

- Baseline starter kernel: **147,734**
- Task 1 (scheduler only): **13,391**
- Task 2 (SIMD only): **14,415**
- Task 3/4/5 era (scheduler+SIMD+interleaving etc): **~2660**
- Task 6/7/8/9 era (constants, running pointers, etc): **2636**
- Task 10/11/12 era (hash multiply_add + utilization diag): **2637**
- Task 13/14/15 era (header cleanup, micro-opt, DCE): **2632**
- Task 16 (scratch-resident full batch across rounds): **2177**
- Task 17 (root cache attempt): **2351**
- Task 17B (revert): **2177**

## Where To Look In Code

- `perf_takehome.py`
  - `KernelBuilder.build_kernel()` (current optimized kernel shape)
  - `KernelBuilder._schedule_vliw()` (dependency-aware scheduler)
  - `KernelBuilder._slot_reads_writes()` (hazard modeling; correctness-critical)
  - `KernelBuilder._optimize_slots()` (DCE pass)
  - `KernelBuilder.build_hash_vec()` / `KernelBuilder.build_hash()` (hash codegen)
  - `analyze_utilization()` / `print_utilization()` (diagnostics)
- `problem.py` / `tests/frozen_problem.py`
  - `Machine.run()` cycle accounting and debug-only bundle behavior
  - ISA semantics for `valu`, `vload`, `load_offset`, and `flow.pause`
  - `reference_kernel2()` yields and trace keys used by debug compares