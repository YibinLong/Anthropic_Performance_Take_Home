# Performance Take-Home: High-Impact Improvements (Prioritized)

This list is ordered by expected impact on cycle count. Each item includes concrete implementation guidance so an agentic LLM can execute it.

1) Implement a real VLIW scheduler / slot packer (largest single win)
Why: The current `KernelBuilder.build()` emits one slot per instruction bundle, wasting almost all slot capacity (ALU 12, VALU 6, load 2, store 2, flow 1). Packing independent ops into the same cycle can yield an order-of-magnitude cycle reduction.
Where: `perf_takehome.py` (new scheduler + KernelBuilder changes).
How:
- Create an IR for ops with fields: `engine`, `slot`, `reads` (scratch addrs), `writes` (scratch addrs), and an optional `comment`.
- Track last-write cycle per scratch addr. An op is schedulable at cycle C if for every read, `last_write[addr] < C` and for every write, `last_write[addr] < C` (no RAW/WAW in same cycle).
- For each cycle, create a bundle dict with empty lists per engine, fill greedily from a ready queue while respecting `SLOT_LIMITS`.
- When an op is placed at cycle C, update `last_write` for its write set to C.
- Emit bundle list as the program.
- Keep debug ops in separate bundles so they do not constrain packing (or skip them in non-debug builds).
Validate: `python tests/submission_tests.py` (cycle drop should be dramatic even before algorithm changes).

2) Keep input indices/values in scratch for all rounds (eliminate per-round load/store)
Why: The baseline does 2 loads + 2 stores per element per round. These dominate load/store engines and cycles. Keeping inputs in scratch removes almost all memory traffic for inputs.
Where: `perf_takehome.py` inside `KernelBuilder.build_kernel`.
How:
- Allocate scratch arrays: `idx_arr` and `val_arr` of length `batch_size` each.
- At the start, load inputs from memory into these arrays (use `vload` in chunks of `VLEN` if you implement vectorization, or scalar loads if not).
- Run all rounds using only scratch arrays for idx/val.
- At the end, store the scratch arrays back to memory (use `vstore` in chunks of `VLEN`).
- Leave tree values in memory (too large for scratch).
Validate: Run `tests/submission_tests.py`. Results should match because tests only check final memory.

3) Vectorize the inner loop using VALU (process 8 lanes at once)
Why: VLEN=8 means a single VALU op replaces 8 scalar ALU ops. Hashing and index updates are per-element and vector-friendly.
Where: `perf_takehome.py` (KernelBuilder, scratch layout).
How:
- Lay out `idx_arr` and `val_arr` contiguously in scratch to match `VLEN` lanes.
- Precompute vector constants once with `vbroadcast` (e.g., 1, 2, hash constants, `forest_values_p`, `n_nodes`).
- For each vector chunk:
  - Compute `addr_vec = idx_vec + forest_values_p_vec` via `valu '+'`.
  - Gather `node_val_vec` using `load_offset` slots for offsets 0..VLEN-1 (2 loads per cycle).
  - Compute `val_vec ^= node_val_vec` (`valu '^'`).
  - Apply hash stages with `valu` ops (3 per stage, 6 stages).
  - Compute parity and idx update with `valu` ops (see items 4 and 5 below).
- Write results in-place to the same scratch addresses.
Validate: Compare results to `reference_kernel2` via submission tests.

4) Remove `flow select` for parity: use `idx = 2*idx + 1 + (val & 1)`
Why: `flow` has only 1 slot per cycle, making it a bottleneck in a packed schedule. This algebra removes `flow select` entirely for the parity branch.
Where: `perf_takehome.py` in the idx update sequence.
How:
- Replace: `tmp = (val % 2 == 0) ? 1 : 2` with `parity = val & 1`, then `idx = (idx * 2) + 1 + parity`.
- Use `valu '&'` and `valu '+'`/`valu '*'` in vectorized code.
Validate: Ensure parity semantics match `val % 2 == 0` (they do for unsigned 32-bit values).

5) Remove `flow select` for wrap: use `idx = idx * (idx < n_nodes)`
Why: Same flow bottleneck. Multiply by a 0/1 predicate replaces the conditional select.
Where: `perf_takehome.py` in wrap step.
How:
- Compute `cond = (idx < n_nodes)` using `alu '<'` or `valu '<'`.
- Replace `idx = cond ? idx : 0` with `idx = idx * cond`.
- Vectorize with `valu '*'`.
Validate: Confirm `idx` becomes 0 when out of bounds; otherwise unchanged.

6) Use vectorized gather with `load_offset` (compute addresses once)
Why: Scalar per-lane address arithmetic + load is expensive. Vector address compute + `load_offset` halves the address ALU count.
Where: `perf_takehome.py` inside the vector chunk loop.
How:
- Compute `addr_vec = idx_vec + forest_values_p_vec` with `valu '+'`.
- For offsets 0..VLEN-1, emit `load_offset(node_val_vec, addr_vec, offset)` slots. This uses `core.scratch[addr_vec+offset]` as the memory address.
- Schedule these loads across cycles (2 per cycle).
Validate: Compare `node_val_vec` to scalar reference for a few inputs in debug mode.

7) Software-pipeline across vector chunks to saturate load/valu slots
Why: Even with vectorization, load slots (2/cycle) and valu slots (6/cycle) can be underutilized if you process one vector at a time. Interleaving chunks keeps all engines busy.
Where: `perf_takehome.py` scheduler or a manual cycle plan.
How:
- Build an op queue for multiple vector chunks at once (e.g., 2–4 chunks) and let the scheduler interleave them.
- Ensure each chunk’s loads happen early while the previous chunk’s hash/idx ops run.
- Tune the “pipeline depth” (number of in-flight chunks) to saturate load + valu without blowing scratch usage.
Validate: Inspect Perfetto trace and verify high slot utilization; compare cycle counts.

8) Precompute and reuse vector constants (avoid repeated vbroadcast)
Why: Constants are used in every hash stage; broadcasting each time wastes valu slots and cycles.
Where: `perf_takehome.py` (KernelBuilder init section).
How:
- For each scalar constant used in hash or idx update, allocate a vector slot and fill it once using `vbroadcast`.
- Reuse these vector constants across all rounds/chunks.
Validate: Ensure constants are loaded once and reused; verify scratch usage stays within `SCRATCH_SIZE`.

9) Eliminate unused header loads and scratch allocations
Why: The current kernel loads `rounds`, `batch_size`, and `forest_height` even though they are never used after unrolling. Removing them simplifies the program and frees scratch.
Where: `perf_takehome.py` in `build_kernel` initialization.
How:
- Only load `n_nodes`, `forest_values_p`, `inp_indices_p`, `inp_values_p` if needed.
- Remove allocations and `load` ops for unused variables.
Validate: Run tests; no functional change expected.

10) Add a debug/trace build mode that inserts pauses and debug compares only when needed
Why: `pause` and debug instructions cost cycles in submission mode (enable_pause is False but the bundle still counts). Removing them saves cycles while preserving a debug path.
Where: `perf_takehome.py` (KernelBuilder flags, build_kernel signature).
How:
- Add a `debug=False` parameter to `build_kernel`.
- If `debug` is True, include `pause` and `debug compare` ops; otherwise omit them entirely.
- Keep perf_takehome tests using `debug=True`; submission tests will use `debug=False`.
Validate: Run `perf_takehome.py` tests with debug enabled; run submission tests with debug disabled.

11) Introduce a lightweight IR + optimizer pass (dead-code removal, constant folding)
Why: As you add vectorization and scheduling, it becomes easy to generate redundant ops (e.g., repeated const loads or unused temporaries). An optimizer keeps the schedule tight.
Where: `perf_takehome.py` (new IR layer).
How:
- Build ops into an IR list first (not direct instruction bundles).
- Add passes: remove ops whose outputs are never read; dedupe constant loads; coalesce identical `vbroadcast`.
- Then schedule.
Validate: Confirm correctness and fewer ops; cycle count should drop slightly.

12) Optional: Implement loop-based kernel for easier codegen (trade-off)
Why: Unrolling is huge and makes scheduling complex. Looping reduces code size and can simplify scheduling, but adds branch overhead. It may help iteration speed while prototyping.
Where: `perf_takehome.py` (new loop-based builder).
How:
- Use `flow.cond_jump_rel` and `flow.add_imm` to build loops over batch and rounds.
- Keep the loop kernel vectorized; loop counters can be scalar.
- Compare cycle impact; keep unrolled version if faster.
Validate: Compare cycles; choose whichever is faster.

13) Optional: Cache top tree levels in scratch
Why: Indices start at root and may hit top nodes frequently. Caching a small prefix of `forest_values` can reduce memory loads.
Where: `perf_takehome.py` (init section and gather path).
How:
- Copy the first `k` tree values (e.g., 31 or 63) into scratch.
- When loading node values, test `idx < k`; if true, load from scratch; else load from memory.
- Use the multiply-by-condition trick to avoid flow selects where possible.
Validate: Benchmark; keep only if cycles improve.

14) Add slot-utilization diagnostics from the trace
Why: To tune scheduling, you need visibility into how many slots are used per cycle for each engine.
Where: `problem.py` tracing or a new analysis script.
How:
- Post-process `trace.json` to compute utilization per engine.
- Print summary stats (avg slots used per engine per cycle).
Validate: Use this to guide scheduling tweaks.

15) Small arithmetic simplifications throughout
Why: The inner loop is huge; small savings per element compound.
Where: `perf_takehome.py`.
How:
- Replace `% 2` with `& 1` in scalar or vector paths.
- Use `add_imm` where it can replace `load const + alu +` in looped code.
- Reuse temporaries to reduce scratch pressure (but preserve scheduling constraints).
Validate: Confirm exact output; measure cycles.
