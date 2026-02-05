# Optimization Session Report: Interleave Group Grid Search + Configurable Tuning

## Summary (2026-02-05)

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Cycle count | 1764 | 1566 | -198 (-11.2%) |
| Speedup over baseline | 83.75x | 94.34x | +10.6x |
| Tests passing | 5/9 | 6/9 | +1 |

New speed test passed: `test_opus45_2hr` (< 1579 cycles).

Command used:
```
python tests/submission_tests.py 2>&1
```

Current failures (as of this report):
- `test_sonnet45_many_hours` (< 1548)
- `test_opus45_11hr` (< 1487)
- `test_opus45_improved_harness` (< 1363)

---

## What I changed

### 1) Grid-searched interleave groups and increased default to 26

**Rationale:** After depth-aware gather elimination (depths 0..2), the kernel became VALU-heavy. The earlier best setting (12 groups) was tuned for the old load-bound shape. I ran a grid search to re-tune interleave groups under the new VALU pressure.

**Result:** Best cycle count at `interleave_groups = 26`.

Grid results (frozen harness, correctness checked):
```
g=20 cycles=1689
 g=21 cycles=1659
 g=22 cycles=1628
 g=23 cycles=1600
 g=24 cycles=1572
 g=25 cycles=1569
 g=26 cycles=1566  <-- best
 g=27 cycles=1581
 g=28 cycles=1598
 g=29 cycles=1616
```

**Implementation detail:**
- `KernelBuilder` now accepts `interleave_groups` (default 26) and an optional `interleave_groups_early` (defaults to the same value). Allocation uses `max(...)` to keep scratch deterministic.
- Scheduling uses a per-round `regs_list` so the early/late split can be tested without changing allocation.
- Kept the split logic even though early/late settings did not beat the unified best. This makes future tuning easier.

### 2) Minor debug-path cleanup

Depth 0 debug compare now uses `vec_node0` directly, avoiding a redundant `valu '+'` for `node_val` in debug builds.

---

## How I arrived at the conclusion

1) The post-depth-optimization kernel became VALU-heavy (load engine no longer saturated).
2) Interleave groups control how many independent vectors are in flight and how well VALU slots are packed.
3) I ran a grid sweep (6..29), using the frozen harness to avoid noise.
4) The cycle count followed a clear U-shaped curve with a minimum at 26 groups.
5) Verified correctness for each tested value by running the reference comparison in `tests/submission_tests.py`.

**Key takeaway:** after removing gathers for early depths, the optimal interleave group count shifted dramatically upward. This was the single strongest lever left once we became VALU-bound.

---

## Attempted but reverted (failed correctness)

1) **Depth-3 node selection (nodes 7..14) to skip gathers**
   - Idea: extend depth-aware selection to avoid another full round of gathers.
   - Implemented 3-bit arithmetic selection for nodes 7..14.
   - Outcome: incorrect outputs. Debug compares showed node values wrong in the depth-0/1 path due to scheduling interference.
   - Conclusion: needs a safer design (likely additional dependency anchoring or segmentation), but it did not survive VLIW scheduling as implemented.

2) **Running pointer prelude/epilogue to remove offset const loads**
   - Idea: remove `const` loads for `offset_addrs` by incrementing a pointer each vector step.
   - Outcome: incorrect outputs across all rounds.
   - Conclusion: pointer dependencies got reordered in VLIW scheduling, causing wrong addresses. This needs stronger dependency constraints or explicit barriers to be safe.

---

## Current bottleneck (after tuning)

Utilization (approximate):
- VALU: ~96% (near saturation)
- Load: ~85%
- ALU/Store/Flow: low

The kernel is now **VALU-bound**, not load-bound. This means future wins likely require **reducing VALU operations**, not just improving scheduling.

---

## Research leads (for future work)

These are external ideas that informed possible next steps. URLs are included in a code block to avoid raw links in text.

```
https://www.kdd.org/kdd2018/accepted-papers/view/rapidscorer-fast-tree-ensemble-evaluation-by-maximizing-compactness-in-data
https://docs.lib.purdue.edu/open_access_dissertations/162/
https://arxiv.org/abs/2505.01180
```

Interpretation:
- **RapidScorer / compact tree evaluation**: suggests that reducing per-node work (via compact layout or precomputation) can dominate speedups. For our kernel, this points toward caching a small top-level subtree or precomputing early-depth transitions.
- **SIMTree-style traversal grouping**: dynamic regrouping of inputs with similar traversal paths can improve SIMD efficiency. In our ISA, this might map to cheap bucketization by `idx` depth (or parity bits) to increase reuse and reduce VALU ops.
- **Branchless SIMD search structures**: gapped SIMD-friendly node layouts reduce per-node branching and ALU ops. This hints at building a tiny LUT for upper depths (if scratch allows) to reduce VALU pressure further.

---

## Future ideas to explore

1) **Depth-3 or depth-4 LUT with explicit dependency anchoring**
   - The depth-3 arithmetic selector is correct in scalar math, but scheduling broke it. Consider isolating the selection with explicit dependencies (e.g., via a single combined op or temporary registers that cannot be hoisted) or splitting into a tiny barriered segment.

2) **Top-level subtree cache in scratch**
   - Caching nodes 0..14 is already done. Extending to nodes 0..30 (depth 4) might be feasible given scratch headroom and could remove another round of gathers.

3) **Reduce VALU chain length**
   - Hash simplification already removed some ops. Any further algebraic fusion (or a small LUT for early rounds) might lower the tail drain and drop another ~5-10 cycles.

4) **Micro-scheduler constraints for address-sensitive operations**
   - Running pointers failed due to scheduling reordering. A targeted “no-reorder” marker (a tiny barrier or faux dependency) could enable that optimization safely.

---

## Files touched

- `perf_takehome.py`

## Repro steps

```
python tests/submission_tests.py 2>&1
```

Expected output (as of this report):
- CYCLES: 1566
- Failures: 3 (thresholds <1548, <1487, <1363)
