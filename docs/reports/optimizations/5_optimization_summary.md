# Optimization Session Report: Depth-1/2 VALU Reductions (2026-02-05)

## Summary

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Cycle count | 1563 | 1547 | -16 (-1.0%) |
| Speedup over baseline | 94.52x | 95.50x | +0.98x |
| Tests passing | 6/9 | 7/9 | +1 |

New speed test passed: `test_sonnet45_many_hours` (< 1548 cycles).

Command used:
```
python tests/submission_tests.py
```

Remaining failures:
- `test_opus45_11hr` (< 1487)
- `test_opus45_improved_harness` (< 1363)

## What I changed (and why it helped)

### 1) Depth-1 node selection: remove a VALU op

**Original math**
```
node_val = node1 + (idx - 1) * (node2 - node1)
```

**Problem:** This required a `vec_idx - 1` followed by `multiply_add`, i.e., two VALU ops in the hot path.

**Rewrite:**
```
node_val = idx * (node2 - node1) + (node1 - (node2 - node1))
```

**Implementation details:**
- Precompute `vec_node21_diff = node2 - node1` (already present).
- Add `vec_node1_minus_diff = node1 - vec_node21_diff` in the header.
- Replace the subtract+multiply_add with a single `multiply_add` on `idx`.

**Result:** removes one VALU op on every depth-1 vector step (depth 1 occurs twice over 16 rounds). This reduced overall cycles by several ticks.

### 2) Depth-2 node selection: eliminate the extra subtract

Depth 2 selects among nodes 3..6 using two bits. Prior code computed:
- `v01 = node3 + b0*(node4-node3)`
- `v23 = node5 + b0*(node6-node5)`
- `diff = v23 - v01`
- `node_val = v01 + b1*diff`

That is **4 VALU ops** after deriving `b0`/`b1`.

**Rewrite the diff:**
```
diff = (node5 - node3) + b0 * ((node6 - node5) - (node4 - node3))
```

**Implementation details:**
- Precompute `vec_node53_diff = node5 - node3`.
- Precompute `vec_node6543_diff = (node6 - node5) - (node4 - node3)`.
- Use `diff = multiply_add(b0, vec_node6543_diff, vec_node53_diff)`.
- Keep `v01` as before, then `node_val = v01 + b1*diff`.

**Result:** removes one VALU op in depth-2. Depth 2 occurs twice in 16 rounds, so this saves meaningful cycles without changing the load profile.

### 3) Wrap-depth idx update skip (kept, but no cycle change)

At `depth == forest_height`, the next round is depth 0, which overwrites idx directly. In non-debug builds we now skip idx update entirely at that depth. In practice this produced **no measurable cycle improvement**, but it is safe and keeps the hot path simpler.

## Why these changes were safe

- Depth-1/2 node formulas are algebraic identities; no semantic changes.
- All constants are preloaded in the header and remain in scratch (as in existing design).
- The wrap-depth skip only applies when `emit_debug=False`; debug trace correctness remains intact.

## Pitfalls / regressions I hit

1) **Interleave group retuning regressed**
   - `interleave_groups=28` -> 1593 cycles (worse)
   - `interleave_groups=25` -> 1568 cycles (worse)
   - Restored to 26.

2) **Depth-2 gating (only first occurrence) regressed**
   - I tried to use arithmetic selection only for the first depth-2, and gather after wrap. It was correct but slower (1610 cycles), likely due to extra loads.

3) **Splitting paired VALU ops did not help**
   - I split the grouped VALU pairs in `build_hash_vec` to allow more flexible scheduling. Cycle count stayed flat, so I reverted.

## Thought process / how I got here

- The kernel is still VALU-bound (~95% utilization), so the only remaining obvious lever is **reducing VALU op count** in deterministic paths (depth 0/1/2).
- Depth 1 and 2 are the only parts of the hot loop where we can replace data-dependent loads with arithmetic and still guarantee correctness.
- I focused on **algebraic rewrites** that reduce the number of VALU operations without adding new dependencies or loads.
- Both changes were local and low-risk, and the test harness showed a consistent 16-cycle improvement.

## Research I looked at (for ideas)

These papers focus on speeding tree inference by reducing memory traffic or improving SIMD utilization. They are not directly transferable, but they informed the direction of “reduce per-node work, increase SIMD coherence”:

- RapidScorer (compact bitvector tree layout, data-level parallelism)
  https://www.kdd.org/kdd2018/accepted-papers/view/rapidscorer-fast-tree-ensemble-evaluation-by-maximizing-compactness-in-data

- SIMTree (point blocking + traversal splicing for SIMD efficiency)
  https://engineering.purdue.edu/plcl/simtree/

- FastBDT (cache-friendly linear access and integer-centric ops)
  https://arxiv.org/abs/1609.06119

- Register Your Forests (explicit register allocation for tree inference)
  https://arxiv.org/abs/2404.06846

## Additional research-driven ideas for future work

1) **Depth-3 selection with “diff factoring”**
   - Try extending the algebraic selection trick to nodes 7..14. If the VALU reduction outweighs the added scratch consts and ops, this could shave more cycles.

2) **SIMTree-style bucketization by idx bits**
   - Group lanes by low bits of idx (parity / depth buckets) to increase SIMD coherence, potentially enabling a small LUT for common paths.

3) **Top-of-tree scratch caching**
   - RapidScorer-style compact node storage suggests caching a larger top subtree in scratch. This would replace gathers with scratch reads for higher depths.

4) **Explicit scratch register allocation audit**
   - The Register-Your-Forests idea maps to using more scratch temporaries to break false dependencies, especially around address math and hashing.

## Files touched

- `perf_takehome.py`

