# Optimization Improvements for VLIW SIMD Kernel

**Baseline: 147,734 cycles | Target: < 1,363 cycles (~108x speedup)**

This document lists optimizations from most impactful to least. Each improvement is written so an agentic LLM can implement it by reading this description and the source code in `perf_takehome.py` and `problem.py`.

---

## 1. SIMD Vectorization (Expected: ~8x speedup → ~18,500 cycles)

**File to modify:** `perf_takehome.py` — `KernelBuilder.build_kernel()`

**What:** The current implementation processes one batch item at a time (scalar). The architecture supports SIMD with `VLEN=8`, meaning 8 items can be processed in parallel per instruction. Since `batch_size=256 = 32 × 8`, the inner loop iteration count drops from 256 to 32.

**How to implement:**
1. Replace scalar scratch allocations (`tmp_idx`, `tmp_val`, etc.) with vector allocations of length `VLEN` (8 words) using `self.alloc_scratch(name, VLEN)`.
2. Replace scalar loads of `idx` and `val` with `("vload", dest, addr_scratch)` where `addr_scratch` holds the base memory address. `vload` loads 8 contiguous words from memory into 8 consecutive scratch addresses.
3. Replace scalar ALU ops with `valu` ops. The valu engine operates on vectors — `scratch[dest:dest+8] = scratch[a1:a1+8] OP scratch[a2:a2+8]`.
4. Use `("vbroadcast", dest, src)` to broadcast scalar constants (hash constants, `n_nodes`, `two_const`, etc.) to vector registers before the loop.
5. Replace scalar stores with `("vstore", addr_scratch, src)` for contiguous writes of idx and val arrays.
6. **Critical exception — tree node gather:** Tree node loads (`node_val = mem[forest_values_p + idx]`) cannot use `vload` because each of the 8 items has a different `idx`. Use 8 individual `("load_offset", dest, addr_vec, offset)` instructions for offsets 0-7, where `addr_vec` is a vector scratch holding the 8 computed memory addresses (`forest_values_p + idx[i]`). This requires computing addresses first with a valu add: `valu("+", addr_vec, broadcast_forest_p, idx_vec)`.
7. Replace `("flow", ("select", ...))` with `("flow", ("vselect", dest, cond, a, b))` for the vector conditional operations.

**Key constraints:**
- `valu` has limit of 6 slots per cycle
- `vload`/`vstore` use load/store engine slots (limit 2 each per cycle)
- `load_offset` uses load engine slots (limit 2 per cycle), so 8 gather loads = 4 cycles minimum

---

## 2. VLIW Instruction Packing (Expected: ~4-6x additional speedup → ~3,000-4,500 cycles)

**File to modify:** `perf_takehome.py` — `KernelBuilder.build()` and `KernelBuilder.build_kernel()`

**What:** The current `build()` method wraps every single slot in its own instruction bundle (dict), meaning one operation per cycle. The VLIW architecture allows packing multiple independent operations into the same cycle:
- Up to 12 `alu` slots per cycle
- Up to 6 `valu` slots per cycle
- Up to 2 `load` slots per cycle
- Up to 2 `store` slots per cycle
- Up to 1 `flow` slot per cycle

**How to implement:**
1. Stop using the `build()` method entirely. Instead, build instruction bundles directly or write a scheduler.
2. Create a VLIW scheduler that packs independent operations into the same instruction bundle. Two operations are independent if neither reads a scratch address that the other writes to in the same cycle. Key rule: **writes take effect at end of cycle**, so reading a location being written in the same cycle yields the OLD value.
3. Dependency analysis rules:
   - **RAW (Read-After-Write):** If instruction B reads from a scratch address that instruction A writes to AND B needs the NEW value, B must be in a LATER cycle than A.
   - **WAR (Write-After-Read):** NOT a hazard — writes happen at end of cycle, reads see old values. You CAN read and write the same address in one cycle.
   - **WAW (Write-After-Write):** If both A and B write to the same address in the same cycle, the result is non-deterministic (dict last-write-wins). Avoid this.
4. Respect slot limits per engine per cycle.

**Scheduling algorithm (list scheduling):**
```
For each operation, track: engine, slot_tuple, set_of_scratch_addrs_read, set_of_scratch_addrs_written
Build dependency graph: op B depends on op A if A writes to an address that B reads
Topological sort, then greedily pack into cycles respecting slot limits
```

**Alternative simpler approach:** Instead of a general scheduler, manually construct packed bundles by analyzing the kernel's operation sequence. Group operations that use different engines or are independent into the same bundle.

---

## 3. Loop-Based Execution with Jumps (Expected: smaller program, prerequisite for deep optimization)

**File to modify:** `perf_takehome.py` — `KernelBuilder.build_kernel()`

**What:** The current implementation fully unrolls all 16 rounds × 256 iterations = 4,096 loop bodies. Using `jump` / `cond_jump` instructions creates loops, reducing program size from ~150K instructions to ~100-200 and making VLIW packing tractable.

**How to implement:**
1. Allocate scratch registers for loop counters: `round_counter`, `batch_counter`.
2. Use `("load", ("const", counter, 0))` to initialize counters.
3. Emit the loop body once.
4. At end of inner loop body, increment pointer: `("flow", ("add_imm", batch_ptr, batch_ptr, VLEN))` for vectorized loop.
5. Compare counter to limit: `("alu", ("<", cond, batch_counter, batch_limit_scratch))`.
6. Conditional jump back: `("flow", ("cond_jump", cond, loop_start_pc))`.
7. For the outer round loop, reset batch counter/pointers and increment round counter similarly.
8. Use `("flow", ("halt",))` at the end.

**Key details:**
- `cond_jump` uses the `flow` engine (limit 1 per cycle), same as `add_imm`. They CANNOT be in the same cycle.
- Optimal loop overhead: cycle 1 = `add_imm` (flow) + `alu <` comparison; cycle 2 = `cond_jump` (flow). Total: 2 cycles per iteration for loop control.
- Track `len(self.instrs)` before emitting loop body to know the jump target PC address.
- Remove all `pause` and `debug` instructions from the loop body — submission tests disable them (`enable_pause=False`, `enable_debug=False`). They add no cycles when disabled but clutter the program.

---

## 4. Hash Stage Pair/Combine Parallelism (Expected: reduces hash from 18 to 12 cycles per invocation)

**File to modify:** `perf_takehome.py` — `KernelBuilder.build_hash()`

**What:** Each hash stage computes:
```
tmp1 = a OP1 const1    (reads a)
tmp2 = a OP3 const3    (reads a)
a    = tmp1 OP2 tmp2   (reads tmp1, tmp2)
```
`tmp1` and `tmp2` are INDEPENDENT (both only read `a`). They can execute in the same cycle. The combine (`a = tmp1 OP2 tmp2`) must wait one cycle.

**How to implement:**
1. Pack the two pair ops into the same instruction bundle:
   ```python
   bundle = {"valu": [
       (op1, tmp1, val_hash, const1_vec),
       (op3, tmp2, val_hash, const3_vec),
   ]}
   ```
2. In the next bundle, do the combine:
   ```python
   bundle = {"valu": [
       (op2, val_hash, tmp1, tmp2),
   ]}
   ```
3. Each hash stage = 2 cycles. 6 stages = 12 cycles per hash.

**Critical for interleaving:** This structure leaves unused valu slots (4 in pair cycle, 5 in combine cycle) that can be filled by operations from other interleaved vector groups.

---

## 5. Pre-broadcast All Constants Before the Loop (Expected: saves ~100+ cycles, prerequisite for vectorization)

**File to modify:** `perf_takehome.py` — `KernelBuilder.build_kernel()`

**What:** The hash function uses 6 constant values and the kernel uses several other constants (`0`, `1`, `2`, `n_nodes`, `forest_values_p`). Instead of loading these per-iteration or using scalar constants with broadcasts in the loop, pre-load and broadcast them to vector registers once before the loop.

**How to implement:**
1. Allocate vector scratch space for each constant: `const_hash0_vec[8]`, `const_hash1_vec[8]`, etc.
2. Before the loop:
   ```python
   scalar_tmp = self.alloc_scratch("scalar_tmp")
   self.add("load", ("const", scalar_tmp, HASH_STAGES[0][1]))  # e.g., 0x7ED55D16
   self.add("valu", ("vbroadcast", const_hash0_vec, scalar_tmp))
   ```
3. Also broadcast: `zero_vec`, `one_vec`, `two_vec`, `n_nodes_vec`, `forest_values_p_vec`.
4. These vector constants are then used directly in `valu` operations throughout the loop.

**Scratch budget:** 6 hash constants × 8 + ~6 utility constants × 8 = ~96 scratch words. Well within the 1536 limit.

---

## 6. Eliminate `flow select` for Parity and Wrap (Expected: saves 2 flow slots per iteration, removes bottleneck)

**File to modify:** `perf_takehome.py` — `KernelBuilder.build_kernel()`

**What:** `flow` engine has only 1 slot per cycle, making `select`/`vselect` a serialization bottleneck. The parity branch and index wrap can both be computed with pure ALU/VALU ops.

**How to implement:**

**Parity (replacing `select`):**
The original: `branch = 1 if val%2==0 else 2`. Equivalently: `branch = (val & 1) + 1`.
- When `val` is even: `val & 1 = 0`, `branch = 1`. Correct.
- When `val` is odd: `val & 1 = 1`, `branch = 2`. Correct.
```python
# Replace:  %, ==, select  (3 ops, 1 flow)
# With:     &, +            (2 valu ops, 0 flow)
("valu", ("&", parity_vec, val_vec, one_vec))
("valu", ("+", branch_vec, parity_vec, one_vec))
```

**Wrap (replacing `select`):**
The original: `idx = 0 if idx >= n_nodes else idx`. Equivalently: `idx = idx * (idx < n_nodes)`.
```python
# Replace:  <, select  (1 alu + 1 flow)
# With:     <, *        (2 valu ops, 0 flow)
("valu", ("<", cond_vec, idx_vec, n_nodes_vec))
("valu", ("*", idx_vec, idx_vec, cond_vec))
```

**Combined idx update:**
```python
# idx = 2*idx + (val&1) + 1, then wrap
("valu", ("&", parity_vec, val_vec, one_vec))     # parity = val & 1
("valu", ("+", branch_vec, parity_vec, one_vec))   # branch = parity + 1
("valu", ("<<", idx_vec, idx_vec, one_vec))         # idx = idx * 2 (shift left)
("valu", ("+", idx_vec, idx_vec, branch_vec))       # idx = idx + branch
("valu", ("<", cond_vec, idx_vec, n_nodes_vec))     # cond = idx < n_nodes
("valu", ("*", idx_vec, idx_vec, cond_vec))          # idx = idx * cond (wrap)
```
Note: `&` and `<<` are independent of each other (both read only `val_vec` and `idx_vec` respectively). They can be packed into the same cycle. Similarly `+`(branch) and the second `+`(idx) can potentially be packed if their reads don't conflict.

---

## 7. Software Pipelining / Multi-Group Interleaving (Expected: ~3-4x additional speedup → ~1,000-1,500 cycles)

**File to modify:** `perf_takehome.py` — `KernelBuilder.build_kernel()`

**What:** The hash function has a 12-cycle serial dependency chain. The gather takes 4 cycles. By interleaving multiple independent vector groups, we overlap computation of one group with loads of another, utilizing all engine slots simultaneously.

**How to implement:**

**Step 1 — Allocate multiple register sets:**
Allocate 2-4 independent sets of vector scratch registers. Each set needs:
- `idx_vec[8]` — current indices
- `val_vec[8]` — current values
- `node_val_vec[8]` — gathered node values
- `addr_vec[8]` — computed memory addresses
- `tmp1_vec[8]`, `tmp2_vec[8]` — hash temporaries
Total per set: ~48 scratch words. 4 sets = 192 words.

**Step 2 — Pipeline stages:**
Define pipeline stages for each vector group:
- **LOAD:** vload idx, vload val (2 load slots, 1 cycle)
- **ADDR:** compute addresses = forest_values_p + idx (1 valu, 1 cycle)
- **GATHER:** 8 × load_offset for node_val (2 load slots/cycle, 4 cycles)
- **HASH_PREP:** XOR val with node_val (1 valu, 1 cycle)
- **HASH:** 6 stages × 2 cycles = 12 cycles
- **IDX_UPDATE:** parity + shift + add + compare + multiply (3-4 cycles)
- **STORE:** vstore idx, vstore val (2 store slots, 1 cycle)

**Step 3 — Interleave across groups:**
Build the instruction sequence so that in each cycle, different groups are at different pipeline stages. Key insight: load/store engines and valu engine are independent and can run in parallel.

Example with 2-group interleave (A and B):
```
Cycle 1:  A.LOAD (load engine)
Cycle 2:  A.ADDR (valu) + B.LOAD (load engine)
Cycle 3:  A.GATHER[0-1] (load) + B.ADDR (valu)
Cycle 4:  A.GATHER[2-3] (load) + B.GATHER_PREP...
...
Cycle N:  A.HASH_STAGE_K (valu) + B.GATHER (load) + prev.STORE (store)
```

**Step 4 — Fill valu slots across groups during hash:**
With 6 valu slots per cycle and hash using 1-2 valu per stage-cycle:
- Group A's combine (1 valu) + Group B's pair (2 valu) = 3 valu per cycle
- With 4 groups: up to 6 valu slots filled per cycle

**Estimated throughput:** With 4-group interleaving, effective per-group cost ≈ 3-4 cycles. 512 groups / 4 interleave × ~14 cycles per batch of 4 = ~1,800 cycles. With tighter scheduling, can approach ~1,400 cycles.

---

## 8. Optimize Address Computation with Running Pointers (Expected: saves ~1 cycle per iteration)

**File to modify:** `perf_takehome.py` — `KernelBuilder.build_kernel()`

**What:** Batch indices and values are contiguous in memory. Instead of computing `inp_indices_p + i*VLEN` each iteration, maintain running pointers incremented by VLEN.

**How to implement:**
1. Allocate scalar scratch for `cur_idx_ptr` and `cur_val_ptr`.
2. Initialize: load `inp_indices_p` and `inp_values_p` from memory header into these.
3. Each iteration: `vload` directly from `cur_idx_ptr` and `cur_val_ptr`.
4. After load: `("flow", ("add_imm", cur_idx_ptr, cur_idx_ptr, VLEN))`.
5. At round boundary, reset pointers by reloading from the base values.

This eliminates per-iteration address-addition ALU operations.

---

## 9. Use `multiply_add` for Applicable Hash Stages (Expected: saves ~2-4 valu slots total)

**File to modify:** `perf_takehome.py` — `KernelBuilder.build_hash()`

**What:** The valu engine supports `("multiply_add", dest, a, b, c)` which computes `dest[i] = a[i] * b[i] + c[i]`. Some hash stages can use this.

**How to implement:**
Examine each hash stage. The pattern is: `a = (a OP1 const1) OP2 (a OP3 const3)`.
For stages where OP2 is `"+"` AND OP3 is `"<<"`:
- `a << N` equals `a * (1 << N)`. Pre-load `1 << N` as a vector constant.
- Then: `result = multiply_add(a, shift_const_vec, a_plus_const1)`.
- This replaces the shift + add with a single multiply_add slot.

Applicable stages (OP2 is `"+"`): stages 0, 2, 3, 4.
Stage 0: `(a + 0x7ED55D16) + (a << 12)` → `multiply_add(a, const_4096_vec, tmp1)` where `tmp1 = a + 0x7ED55D16`.
Stage 2: `(a + 0x165667B1) + (a << 5)` → `multiply_add(a, const_32_vec, tmp1)`.
Stage 3: `(a + 0xD3A2646C) ^ (a << 9)` → OP2 is `"^"`, NOT applicable.
Stage 4: `(a + 0xFD7046C5) + (a << 3)` → `multiply_add(a, const_8_vec, tmp1)`.

Wait — `multiply_add` computes `a*b + c`. We need `(a OP1 const1) + (a * shift_const)`. That's `c + a*b` = `multiply_add(a, shift_const, tmp1)` where `tmp1 = a OP1 const1`. This works! But it still requires computing `tmp1` first (1 valu), then multiply_add (1 valu). So it's 2 valu ops in 2 cycles instead of 3 valu ops in 2 cycles. Saves 1 valu slot per applicable stage, freeing a slot for interleaved work.

---

## 10. Keep idx/val Arrays in Scratch Between Rounds (Expected: saves load/store cycles)

**File to modify:** `perf_takehome.py` — `KernelBuilder.build_kernel()`

**What:** Currently, idx and val are loaded from memory and stored back each iteration. Since batch_size=256 and SCRATCH_SIZE=1536, we can keep both arrays (256 + 256 = 512 words) in scratch, only loading from memory at the start and storing at the end.

**How to implement:**
1. Allocate scratch arrays: `idx_scratch[256]` and `val_scratch[256]`.
2. At kernel start, load all 256 idx and 256 val values from memory into scratch using `vload` loops (32 vloads for idx + 32 for val = 64 loads, at 2/cycle = 32 cycles).
3. During the main loop, read/write idx and val from scratch directly (no memory loads/stores needed — just scratch-to-scratch via ALU/VALU operations).
4. At kernel end, store all values back to memory using `vstore` (32 cycles).

**Wait — critical issue:** ALU/VALU operations read from fixed scratch addresses, not computed addresses. The idx and val vectors for each inner loop iteration are at different scratch offsets. Since the loop body is reused (with jumps), you can't hardcode the scratch offset. **Solution:** Instead of keeping ALL 256 items in scratch, use `vload`/`vstore` each inner iteration but avoid redundant address computation (see improvement #8). The scratch approach only works if you fully unroll the inner loop (batch dimension), which conflicts with improvement #3.

**Revised approach:** If using loops (improvement #3), keep a VLEN-sized working set in scratch vectors (this is inherent in vectorization). The vload/vstore per iteration is unavoidable but fast (1 cycle each for contiguous access). If NOT using loops (fully unrolled), you can reference different scratch offsets per unrolled iteration, but the program becomes huge.

**Assessment:** This improvement is mostly superseded by improvements #1 and #3. The real savings come from vectorization (fewer iterations) and VLIW packing (overlapping loads with computation). Mark as optional.

---

## 11. Minimize Scratch Register Pressure for Deeper Interleaving (Expected: enables 4+ group interleave)

**File to modify:** `perf_takehome.py` — `KernelBuilder.build_kernel()`

**What:** Scratch space is 1536 words. With 4-group interleaving, each group needs ~48 words of vector scratch, plus ~96 for constants, plus ~20 for scalars = ~308 total. That's fine. But with 8-group interleaving (to maximize throughput), we'd need ~480 words for groups + 116 for overhead = ~596. Still fine. The limit is ~20 groups before we run out.

**How to implement:**
1. Analyze the liveness of each vector register — when is it first written and last read?
2. After a vector register is no longer needed, reuse its scratch address for a different purpose.
3. For example, `node_val_vec` is only needed between the gather and the XOR. After XOR, its scratch space can be reused for hash temporaries.
4. `addr_vec` is only needed during gather. After gather completes, reuse for something else.
5. With careful reuse, each group might need only ~32 words instead of ~48.

---

## 12. Optimize Loop Overhead (Expected: saves 2-4 cycles per round transition)

**File to modify:** `perf_takehome.py` — `KernelBuilder.build_kernel()`

**What:** The inner loop (batch iterations) runs 32 times (256/VLEN). The outer loop (rounds) runs 16 times. Loop overhead per iteration is ~2 cycles. Over 512 total iterations, that's ~1024 cycles of overhead. Reducing this helps.

**How to implement:**
1. Combine `add_imm` and comparison into one cycle (they use different engines: flow + alu).
2. Use `cond_jump` in the next cycle.
3. For the outer loop: only 16 iterations, so 32 cycles overhead — minimal.
4. Consider partial unrolling of the inner loop (e.g., process 2 vector groups per iteration) to halve the loop overhead, but this increases register pressure.
5. Use `cond_jump_rel` (relative jump) instead of `cond_jump` (absolute) if it simplifies address calculation.

---

## 13. Exploit Write-After-Read Freedom for Tighter Scheduling (Expected: saves scattered cycles throughout)

**File to modify:** `perf_takehome.py` — VLIW scheduler

**What:** In this architecture, writes take effect at end of cycle. You can read a register and overwrite it in the same cycle — the read gets the old value. This is crucial for in-place operations like `val = val ^ node_val` where the result overwrites `val`.

**How to implement:**
- In the VLIW scheduler's dependency analysis, do NOT add a dependency edge for WAR (Write-After-Read) hazards.
- Example: `valu("^", val_vec, val_vec, node_vec)` reads `val_vec` and writes `val_vec`. Another instruction reading `val_vec` in the same cycle will see the OLD value. This is safe and should be allowed.
- This allows scheduling the XOR and subsequent operations more tightly.

---

## 14. Remove All Debug and Pause Instructions (Expected: saves a few cycles + simplifies scheduling)

**File to modify:** `perf_takehome.py` — `KernelBuilder.build_kernel()`

**What:** The submission harness sets `enable_pause=False` and `enable_debug=False`. Debug-only bundles (containing only debug engine slots) don't count as cycles. However, removing them entirely simplifies the instruction stream and avoids any edge cases.

**How to implement:**
- Don't emit any `("debug", ...)` or `("flow", ("pause",))` instructions in the optimized kernel.
- Optionally add a `debug=False` parameter to `build_kernel()` to preserve a debug path for development.
- Keep at most one `("flow", ("pause",))` or use `("flow", ("halt",))` at the end.

---

## 15. Use Shift Instead of Multiply for `idx * 2` (Expected: minor — 1 valu slot saved per iteration)

**File to modify:** `perf_takehome.py` — `KernelBuilder.build_kernel()`

**What:** `idx * 2` can be computed as `idx << 1` using a left shift. Shifts may have different scheduling characteristics than multiplies on some architectures (though in this simulator they're equivalent in cost). The main benefit is clarity and consistency with the bit-manipulation approach.

**How:** Replace `("valu", ("*", idx, idx, two_vec))` with `("valu", ("<<", idx, idx, one_vec))`.

---

## 16. Fully Unroll Inner Loop for Maximum VLIW Packing (Alternative to #3)

**File to modify:** `perf_takehome.py` — `KernelBuilder.build_kernel()`

**What:** If using a general VLIW scheduler (improvement #2), fully unrolling the inner loop (32 vector iterations per round) allows the scheduler to find maximum parallelism across iterations. This eliminates loop overhead entirely but creates a large program.

**Trade-off vs. loops (improvement #3):**
- Unrolled: no loop overhead, maximum scheduling freedom, huge program (but program size doesn't affect cycle count).
- Looped: tiny program, 2 cycles overhead per iteration (32 × 16 = 1024 cycles total overhead).
- For cycle counts below ~2000, the 1024 cycles of loop overhead may be acceptable if the loop body is extremely well packed.

**Recommendation:** Start with loops for development speed, then try unrolling if you need to squeeze out the last few hundred cycles. With a good scheduler, unrolling the inner loop + keeping the outer loop might be optimal (unroll 32 vector iterations, loop over 16 rounds = 32 cycles of round-loop overhead).

---

## 17. Diagnostic: Build a Slot Utilization Analyzer (Expected: guides all other optimizations)

**File to modify:** New script or addition to `perf_takehome.py`

**What:** To optimize VLIW packing, you need visibility into how many slots are actually used per cycle for each engine. Building a diagnostic tool to analyze the generated instruction bundles helps identify underutilized engines.

**How to implement:**
```python
def analyze_utilization(instrs):
    from collections import Counter
    utilization = {engine: [] for engine in SLOT_LIMITS if engine != "debug"}
    for instr in instrs:
        for engine in utilization:
            utilization[engine].append(len(instr.get(engine, [])))
    for engine, counts in utilization.items():
        avg = sum(counts) / len(counts) if counts else 0
        print(f"{engine}: avg {avg:.2f}/{SLOT_LIMITS[engine]} slots used, "
              f"max {max(counts)}, cycles with >0: {sum(1 for c in counts if c > 0)}")
```

This tells you, for example, "valu uses only 2/6 slots on average → room to interleave more work."

---

## Summary: Recommended Implementation Order

1. **Phase 1 — Foundations (target < 18,532 cycles):**
   - Improvement #3: Convert to loop-based execution
   - Improvement #14: Remove debug/pause
   - Improvement #2 (basic): Manual VLIW packing of obviously independent ops

2. **Phase 2 — Vectorization (target < 5,000 cycles):**
   - Improvement #1: SIMD vectorization with valu/vload/vstore
   - Improvement #5: Pre-broadcast constants
   - Improvement #4: Hash pair/combine parallelism
   - Improvement #6: Eliminate flow selects for parity/wrap

3. **Phase 3 — Tight Scheduling (target < 2,000 cycles):**
   - Improvement #2 (full): General VLIW scheduler
   - Improvement #8: Running pointers
   - Improvement #13: WAR freedom in scheduler
   - Improvement #12: Loop overhead optimization

4. **Phase 4 — Deep Pipelining (target < 1,500 cycles):**
   - Improvement #7: Multi-group interleaving / software pipelining
   - Improvement #11: Scratch register reuse for deeper interleaving
   - Improvement #9: multiply_add for hash stages

5. **Phase 5 — Final Squeeze (target < 1,363 cycles):**
   - Improvement #16: Partial or full unrolling of inner loop
   - Improvement #17: Utilization analysis to find remaining gaps
   - Fine-tune interleave depth and scheduling

### Quick Reference: Architecture Constraints

| Engine | Slots/Cycle | Key Instructions |
|--------|-------------|-----------------|
| `alu` | 12 | `+`, `-`, `*`, `//`, `^`, `&`, `\|`, `<<`, `>>`, `%`, `<`, `==` |
| `valu` | 6 | Same ops on vectors of 8, plus `vbroadcast`, `multiply_add` |
| `load` | 2 | `load` (scalar indirect), `load_offset` (vector element indirect), `vload` (contiguous vector), `const` (immediate) |
| `store` | 2 | `store` (scalar indirect), `vstore` (contiguous vector) |
| `flow` | 1 | `select`, `vselect`, `add_imm`, `jump`, `cond_jump`, `cond_jump_rel`, `jump_indirect`, `halt`, `pause`, `coreid`, `trace_write` |

### Key Semantics
- All arithmetic is modulo 2^32
- Writes take effect at END of cycle (reads see old values within same cycle)
- `vload`/`vstore` operate on CONTIGUOUS memory (base address is scalar in scratch)
- `load_offset(dest, addr, offset)`: loads `mem[scratch[addr+offset]]` into `scratch[dest+offset]` — useful for gather
- `vselect(dest, cond, a, b)`: per-element select based on `cond[i] != 0`

### Test Parameters
- `forest_height=10`, `n_nodes=2047`, `batch_size=256`, `rounds=16`
- `VLEN=8`, `SCRATCH_SIZE=1536`, `N_CORES=1`

### Validation
```bash
git diff origin/main tests/    # Must be empty — never modify tests/
python tests/submission_tests.py  # Shows which thresholds you pass
```
