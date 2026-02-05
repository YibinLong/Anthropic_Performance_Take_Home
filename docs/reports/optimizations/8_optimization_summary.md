# Optimization Session Report: Depth‑2 Pairwise Select via Flow (2026-02-05)

## Summary

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Cycle count | 1486 | 1478 | -8 (-0.5%) |
| Speedup over baseline | 99.4x | 100.0x | +0.6x |
| Tests passing | 8/9 | 8/9 | no change |

Command used:
```
python tests/submission_tests.py
```

Remaining failure:
- `test_opus45_improved_harness` (< 1363 cycles)

---

## What I changed

### Depth‑2 node selection: pairwise multiply_add + flow vselect

Depth‑2 previously computed the node value using three VALU ops:

```
path = idx - 3
b0 = path & 1
b1 = path >> 1
v01 = node3 + b0*(node4 - node3)
diff = (node5 - node3) + b0 * ((node6 - node5) - (node4 - node3))
node_val = v01 + b1*diff
```

I rewrote this to compute the two pairwise values and select between them with
the flow engine:

```
path = idx - 3
b0 = path & 1
b1 = path >> 1
v01 = node3 + b0*(node4 - node3)
v23 = node5 + b0*(node6 - node5)
node_val = select(b1, v23, v01)
```

Implementation detail (vector path):
- Replaced the last two VALU ops with:
  - `v23 = multiply_add(b0, node65_diff, node5)`
  - `node_val = flow.vselect(b1, v23, v01)`

Header cleanup:
- Removed `vec_node53_diff` and `vec_node6543_diff` scratch allocations and
  their precompute ops, since the new formula doesn’t use them.

Net effect:
- **VALU ops per depth‑2 group: -1**
- **Flow ops per depth‑2 group: +1**

Given the kernel is VALU‑bound and the flow engine is mostly idle, this
decreases the critical resource pressure while staying within the 1‑slot flow
limit.

---

## Thought process / why this works

1) **Identify the bottleneck:** After earlier gather removal, the kernel is
   VALU‑bound. Any reduction in VALU ops tends to show up directly in cycles.

2) **Target depth‑2 selection:** This is one of the few remaining non‑hash
   arithmetic blocks with 3 VALU ops that compute a single node value. It’s
   also perfectly structured for a 2‑way select.

3) **Use flow for the final choice:** The flow engine was under‑utilized. A
   single `vselect` replaces the final multiply_add without disturbing the
   vector dataflow.

4) **Avoid past pitfalls:** Earlier vselect attempts broke correctness due to
   scheduler reordering and register reuse. This version keeps dependencies
   explicit:
   - `b1` is computed in `vec_node_val` and consumed immediately as the select
     condition.
   - The scheduler sees a strict RAW dependency from the `>>` to `vselect`
     (since `vselect` reads `b1`), so it cannot hoist the select above its
     input.

Result: correctness preserved; cycles reduced from 1486 → 1478.

---

## Bugs / pitfalls encountered

None in this change set. However, earlier flow‑select attempts in depth‑2 failed
because of scratch register reuse and weak dependency anchoring, so I kept the
 select isolated and dependency‑visible. This is why the design uses just one
flow select instead of a full vselect tree for nodes 3..6.

---

## Research consulted (conceptual inspiration)

These sources informed the “reduce per‑node work and restructure selection”
approach, even though the ISA is custom:

```
RapidScorer (compact tree evaluation): 
https://www.kdd.org/kdd2018/accepted-papers/view/rapidscorer-fast-tree-ensemble-evaluation-by-maximizing-compactness-in-data

SIMTree (lane regrouping / traversal splicing):
https://engineering.purdue.edu/plcl/simtree/

Register Your Forests (explicit register allocation for BDT inference):
https://arxiv.org/abs/2404.06846

FastBDT (cache‑friendly layout / branchless traversal):
https://arxiv.org/abs/1609.06119

QuickScorer / V‑QuickScorer (bitvector‑based traversal):
https://arpi.unipi.it/handle/11568/945058
```

---

## Additional research‑driven ideas to try next

1) **Depth‑3/4 scratch cache + select tree (RapidScorer‑style compactness)**
   - Preload nodes 7..14 (depth 3) or 15..30 (depth 4) into scratch, then use a
     vselect tree or a structured arithmetic selector to avoid those gather
     rounds entirely.
   - Needs explicit dependency anchoring to prevent scheduler reordering.

2) **SIMD lane bucketization (SIMTree‑style traversal splicing)**
   - Regroup SIMD lanes by low bits of `idx` to increase path coherence.
   - This could allow smaller LUTs or shared node values, reducing VALU ops.

3) **Scratch/register allocation pass (Register Your Forests angle)**
   - Systematically break false WAW/WAR chains so flow selects become safe and
     more aggressive offloads from VALU are possible.

4) **Bitvector‑style traversal (QuickScorer)**
   - Precompute compact path masks for upper depths and replace some arithmetic
     with bitwise selects or table‑driven updates.

5) **Tighter memory layout for early nodes (FastBDT‑style locality)**
   - Explore packing the top of the tree into contiguous regions to enable
     `vload` instead of `load_offset` gathers where possible.

---

## Files touched

- `perf_takehome.py`
- `docs/reports/optimizations/8_optimization_summary.md` (this report)

---

## Repro steps

```
python tests/submission_tests.py
```

Expected output (as of this report):
- CYCLES: 1478
- One remaining failure: `< 1363` threshold
