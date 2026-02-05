# Optimization Session Report: Flow-Branch Select + Interleave Retune (2026-02-05)

## Summary

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Cycle count | 1547 | 1486 | -61 (-3.9%) |
| Speedup over baseline | 95.5x | 99.4x | +3.9x |
| Tests passing | 7/9 | 8/9 | +1 |

New speed test passed: `test_opus45_11hr` (< 1487 cycles).

Command used:
```
python tests/submission_tests.py
```

Remaining failure:
- `test_opus45_improved_harness` (< 1363 cycles)

---

## What I changed

### 1) Move branch selection to the flow engine (vselect)

**Original vector branch update**
```
branch = (val & 1) + 1
```
This was implemented as two VALU ops:
- `tmp = val & 1`
- `branch = tmp + 1`

**New approach**
Use the flow engine to select between constants 1 and 2:
```
cond = val & 1
branch = vselect(cond, 2, 1)
```

**Why it helps**
- The kernel is VALU-bound; freeing VALU slots helps packing.
- Flow engine was effectively idle (0% utilization).
- This removes one VALU op per idx update (depth 0 and depth >0), trading it for a flow op that can be scheduled alongside VALU operations.

**Implementation details**
- Depth 0: `vec_idx` written directly with vselect (since idx is always 0 prior to update).
- Depth >0: same vselect is used to compute `branch`, then `idx = multiply_add(idx, 2, branch)` as before.

### 2) Retuned interleave groups for new VALU/flow balance

The vselect change shifts pressure away from VALU and adds a flow op. Interleave depth affects how well the scheduler can cover this new mix.

Best observed configuration for this kernel shape:
- `interleave_groups = 25`
- `interleave_groups_early = 26` (depth 0..2)

This produced **1486 cycles**, just under the 1487 threshold.

---

## Thought process / how I got here

1. **Identify the bottleneck:** The kernel was still VALU-heavy (~95% utilization). Reducing VALU ops is the only lever that consistently moves cycle count.
2. **Check unused resources:** Flow engine was idle, which is an opportunity to offload a tiny amount of work.
3. **Find an algebraic swap:** The branch update `(val & 1) + 1` can be expressed as a 2-way select between constants 1 and 2, which maps cleanly to `flow.vselect`.
4. **Validate with tests:** vselect change alone improved from 1547 -> 1497 cycles, then retuning interleave groups brought it down to 1486.
5. **Keep the change minimal:** Only the branch computation path changed; idx update and wrap logic stayed intact.

---

## Bugs / pitfalls encountered

### A) Depth-2 node selection via vselect (incorrect)
I attempted to replace the depth-2 arithmetic selection of nodes 3..6 with three `flow.vselect` ops (select node3/4, node5/6, then pick based on b1). This **broke correctness** immediately in submission tests.

**Likely root cause:** vselect operates in the flow engine and writes at end-of-cycle. The sequence relied on overlapping scratch registers (`cond`, `dest`, and inputs) and the scheduler may have reordered them in a way that violated the intended data dependencies. The arithmetic version (VALU multiply_add) is self-contained and stable under scheduling.

**Outcome:** Reverted to the previous depth-2 arithmetic selection.

### B) Interleave group retuning can regress quickly
Tried multiple values:
- `interleave_groups = 27` → 1513 cycles (worse)
- `interleave_groups = 24` → 1518 cycles (worse)
- `interleave_groups_early = 23 or 28` → 1492–1544 cycles (worse)

Only the 25/26 split improved the new schedule.

---

## Research consulted (high-level ideas)

These sources are not directly implementable in this ISA, but they shaped the next-step ideas:

```
RapidScorer (KDD 2018): https://www.kdd.org/kdd2018/accepted-papers/view/rapidscorer-fast-tree-ensemble-evaluation-by-maximizing-compactness-in-data
SIMTree (PACT/OOPSLA): https://engineering.purdue.edu/plcl/simtree/
FastBDT (arXiv 1609.06119): https://arxiv.org/abs/1609.06119
Register Your Forests (arXiv 2404.06846): https://arxiv.org/abs/2404.06846
```

---

## Additional research-driven ideas to explore

1) **Lane bucketization / traversal splicing (SIMTree-inspired)**
   - Dynamically regroup SIMD lanes by low bits of idx or recent path history.
   - Might enable small LUTs for multiple depths or reduce divergence in gather-heavy rounds.

2) **Top-of-tree scratch cache (RapidScorer-inspired compactness)**
   - Store a larger prefix of nodes (e.g., depth 3 or 4) in scratch with a compact index mapping.
   - Combine with arithmetic select or short LUT to bypass additional gather rounds.

3) **Cache-friendly access / layout ideas (FastBDT)**
   - Explore preloading a contiguous slice of tree nodes and indexing linearly for early depths.
   - This may reduce scatter/gather pressure at the cost of extra scratch/const setup.

4) **Explicit scratch allocation pass (Register-Your-Forests angle)**
   - Systematically break false WAW/WAR chains around hash temporaries.
   - The flow-based branch select showed that small scheduling shifts matter; a focused register allocation pass might buy a few more cycles.

---

## File(s) touched

- `perf_takehome.py`

## Repro steps

```
python tests/submission_tests.py
```

Expected output (as of this report):
- CYCLES: 1486
- One remaining failure: `< 1363` threshold
