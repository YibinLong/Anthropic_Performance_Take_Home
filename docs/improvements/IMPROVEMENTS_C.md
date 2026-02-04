# Ranked Improvements (Consolidated Review of IMPROVEMENTS_A.md + IMPROVEMENTS_B.md)

This file ranks the *most impactful* optimizations for this project, using the constraints in `perf_takehome.py` and `problem.py`. Items are merged/deduped from A and B, with notes on prerequisites, risks, and correctness.

Citation key: `(A#)` points to item `#` in `IMPROVEMENTS_A.md`, and `(B#)` points to item `#` in `IMPROVEMENTS_B.md`. Example: **Real VLIW scheduler / slot packer (A1, B2, B13)** appears in A item 1 and B items 2 and 13.

## Architecture Constraints That Drive Impact

- One instruction bundle per cycle; each engine has per-cycle slot limits (`alu` 12, `valu` 6, `load` 2, `store` 2, `flow` 1).
- Writes commit at **end of cycle**; reads in the same cycle see old values. This allows WAR but not RAW if you need the new value.
- No indirect scratch addressing: scratch operands are **static addresses** baked into the program. You cannot index scratch arrays by a runtime value.
- `vload`/`vstore` require **contiguous** memory addresses; gathers require `load_offset`.
- `pause` is a **flow** slot and **does** cost a cycle even if `enable_pause=False`. Debug-only bundles do **not** cost cycles.

## Improvement Checklist

- [x] **1. Real VLIW scheduler / slot packer (A1, B2, B13)**
   - **Why it matters:** Current `KernelBuilder.build()` emits one slot per bundle, wasting almost all parallel capacity. Packing independent ops can yield an order-of-magnitude cycle reduction.
   - **What to do:** Build an IR with `engine`, `reads`, `writes` and schedule into bundles obeying slot limits. Enforce RAW/WAW, **allow WAR**.
   - **Pitfalls:** If you treat WAR as a dependency, you will unnecessarily serialize in-place ops and lose 2-4x potential throughput.
   - **Status:** `_schedule_vliw()` implements dependency-aware bundle packing with proper slot limits.

- [x] **2. SIMD vectorization of the inner loop + gather via `load_offset` (A3, A6, B1)**
   - **Why it matters:** `VLEN=8` reduces batch iterations from 256 to 32 and collapses 8 scalar ALU ops into 1 VALU slot.
   - **What to do:** Use vector scratch regs, `vload`/`vstore` for contiguous inputs/outputs, `valu` for arithmetic. For tree loads, compute `addr_vec = forest_values_p + idx_vec`, then issue 8 `load_offset` (offset 0..7).
   - **Pitfalls:** `vselect` uses the **flow** engine (1 slot), so it can bottleneck. Prefer arithmetic alternatives (see #5).
   - **Status:** Vectorized loop with `vload`/`vstore`, `load_offset` gather, and `build_hash_vec()`.

- [x] **3. Software pipelining / multi-group interleaving (A7, B7, B11)**
   - **Why it matters:** Hash and gather phases have long dependency chains; interleaving multiple vector groups keeps load/valu/store slots saturated.
   - **What to do:** Allocate 2-4 independent vector register sets, then schedule pipeline stages across groups (LOAD -> ADDR -> GATHER -> HASH -> IDX_UPDATE -> STORE).
   - **Pitfalls:** Requires a scheduler or very careful manual bundling; needs enough scratch.
   - **Status:** `interleave_groups=8` with independent per-group scratch register sets.

- [x] **4. Hash stage pair/combine parallelism (B4)**
   - **Why it matters:** Each hash stage has two independent ops from `a` plus a combine op. Pair ops can execute in the same cycle, cutting hash latency per stage from 3 to 2 cycles.
   - **What to do:** Emit two VALU ops in one bundle for `tmp1`/`tmp2`, then combine in the next.
   - **Pitfalls:** Without #1 (packing), this improvement is muted.
   - **Status:** `build_hash_vec()` emits paired op lists `[op1, op3]` with separate combine ops.

- [x] **5. Eliminate flow selects with arithmetic (parity + wrap) (A4, A5, B6)**
   - **Why it matters:** Flow engine has only 1 slot; select/vselect serialize the whole kernel.
   - **What to do:**
     - Parity: `branch = (val & 1) + 1`; `idx = 2*idx + branch`.
     - Wrap: `idx = idx * (idx < n_nodes)`.
   - **Pitfalls:** Make sure to use modulo-2^32 semantics; shift-left is OK for `*2`.
   - **Status:** Uses `(val & 1) + 1` for parity and `idx * (idx < n_nodes)` for wrap.

- [x] **6. Pre-broadcast and reuse constants (A8, B5)**
   - **Why it matters:** Hash stages reuse constants; broadcasting once saves repeated load/broadcast cost and reduces schedule pressure.
   - **What to do:** Allocate vector constants and populate them once before loops.
   - **Pitfalls:** Watch scratch budget when using multiple interleaved groups.
   - **Status:** `vec_const_map` and `scratch_const()` deduplicate and pre-allocate constants.

- [ ] **7. Running pointers for input arrays (B8)**
   - **Why it matters:** Avoid per-iteration `base + i` address arithmetic; pointer increments are cheap and allow packing with ALU/VALU ops.
   - **What to do:** Maintain `cur_idx_ptr` / `cur_val_ptr` and increment with `flow.add_imm`.
   - **Pitfalls:** Flow slots are scarce; schedule increments alongside non-flow ops.

- [x] **8. Loop structure decision (looped vs unrolled) (A12, B3, B12, B16)**
   - **Why it matters:** Loops reduce code size; unrolling can expose more scheduling freedom and eliminate loop overhead.
   - **What to do:**
     - Loops: `cond_jump`/`cond_jump_rel` with ~2 cycles overhead per iteration.
     - Unroll: no loop overhead, but program grows large.
   - **Pitfalls:** Looping prevents "scratch array" tricks that need fixed addresses (#14).
   - **Status:** Looped implementation with `for round in range(rounds)` and nested vector chunk loop.

- [x] **9. Remove pause/debug in submission path (A10, B14)**
   - **Why it matters:** `pause` costs a cycle even when `enable_pause=False`; removing it directly saves cycles.
   - **What to do:** Add a `debug` flag; emit `pause` and debug compares only when debugging.
   - **Pitfalls:** Do not remove pauses if you rely on `reference_kernel2` yield alignment for debugging.
   - **Status:** `emit_debug` flag controls debug/pause emission; filtered out when `False`.

- [ ] **10. `multiply_add` for applicable hash stages (B9)**
   - **Why it matters:** Replaces shift+add with one VALU op for stages where op2 is `+` and op3 is `<<`.
   - **What to do:** For stages 0, 2, 4: `tmp1 = a + const`, then `a = multiply_add(a, shift_const, tmp1)`.
   - **Pitfalls:** Not applicable to XOR or right-shift stages; benefit is modest.

- [ ] **11. Scratch register reuse / liveness-driven packing (B11)**
   - **Why it matters:** Lower scratch usage enables deeper interleaving, which amplifies #3.
   - **What to do:** Reuse `addr_vec`/`node_val_vec` after they're dead.
   - **Pitfalls:** Requires careful tracking to avoid accidental clobbering in the scheduler.

- [ ] **12. Slot utilization diagnostics (A14, B17)**
   - **Why it matters:** Helps you see which engines are underutilized and guides pipelining depth.
   - **What to do:** Post-process `trace.json` or inspect bundles to compute average slots used.

- [ ] **13. Eliminate unused header loads (A9)**
   - **Why it matters:** Removes dead loads of `rounds`, `batch_size`, `forest_height` once unrolled or looped.
   - **What to do:** Load only the headers you use (`n_nodes`, `forest_values_p`, `inp_*_p`).
   - **Pitfalls:** Small gain, but reduces scratch pressure and clutter.

- [ ] **14. Small arithmetic simplifications (A15, B15)** *(partial)*
   - **Why it matters:** Many tiny wins compound in a tight loop.
   - **What to do:** `% 2` -> `& 1`; `*2` -> `<< 1`; use `add_imm` when looping.
   - **Status:** `& 1` for parity is done, but still uses `*2` instead of `<< 1`, and `add_imm` not used.

- [ ] **15. IR optimizer pass (A11)**
   - **Why it matters:** DCE/constant folding can trim redundant ops after vectorization/scheduling.
   - **What to do:** Build ops in IR, run DCE + const-dedup before scheduling.
   - **Pitfalls:** Engineering cost might outweigh cycle savings unless you already have IR.

- [ ] **16. Keep full batch in scratch across rounds (A2, B10) — conditional / likely incompatible**
   - **Why it matters:** Eliminates repeated loads/stores of inputs.
   - **What to do:** Load all 256 idx/val into scratch once, operate in scratch, then store back.
   - **Pitfalls:** **Only works if the inner loop is fully unrolled**, because you cannot index scratch with a runtime variable. With loops, this is not viable.

- [ ] **17. Cache top tree levels in scratch (A13) — likely low ROI**
   - **Why it matters:** In theory, reduces memory loads if indices hit top nodes often.
   - **What to do:** Cache first k nodes; use conditional load path.
   - **Pitfalls:** Requires extra compare/select logic (flow or extra loads) and likely loses unless tree access is heavily biased.

---

## Items Likely Wrong or Unreliable (Placed at Bottom Above)

- **"Keep full batch in scratch across rounds" as a general improvement**: This fails with looped code because scratch addressing is static. It only works with fully unrolled batch loops.
- **"Cache top tree levels in scratch"**: Probably net-negative due to added conditionals and flow bottlenecks, unless access is highly biased.

## Corrections to Misleading Statements in A/B

- **Pause does cost cycles even when disabled**: `pause` is a flow slot, so it increments cycles whenever present. Debug-only bundles do *not* count.
- **Loops are not a prerequisite**: Looping is a trade-off (code size vs loop overhead). Unrolling can be better for peak performance with a good scheduler.
