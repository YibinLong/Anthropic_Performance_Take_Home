# Optimization Session Report: Depth-2 Flow Select Attempt (Reverted)

## Summary (2026-02-05)

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Cycle count | 1486 | N/A | Reverted (incorrect) |
| Tests passing | 8/9 | 0/9 during attempt | Correctness broke |

Command used:
```
python tests/submission_tests.py
```

Final state: **reverted** to the previous, correct kernel at **1486 cycles**.

---

## What I tried

### Depth-2 node selection via flow `vselect` (reverted)

**Goal:** Reduce VALU pressure by replacing the depth‑2 arithmetic selection of nodes 3..6 with flow-engine selects, since the flow engine is largely idle and the kernel is VALU‑bound.

**Original depth‑2 path (correct):**
```
path = idx - 3
b0 = path & 1
b1 = path >> 1
v01 = node3 + b0*(node4 - node3)
diff = (node5 - node3) + b0 * ((node6 - node5) - (node4 - node3))
node_val = v01 + b1*diff
```

**Attempted rewrite (incorrect):**
```
sel0 = vselect(b0, node4, node3)
sel1 = vselect(b0, node6, node5)
node_val = vselect(b1, sel1, sel0)
```

I replaced three VALU ops (`multiply_add` chain) with three flow `vselect` ops, expecting to trade VALU pressure for flow usage.

---

## Why it failed

The attempt **broke correctness immediately** in `tests/submission_tests.py` and also in a smaller debug harness. The first mismatch occurred at **round 0, depth 0**, indicating that the problem wasn’t just depth‑2 logic but **scheduler reordering with overlapping scratch registers**:

- The flow `vselect` operates via the flow engine and writes at end‑of‑cycle.
- The scheduler can reorder instructions freely as long as it thinks dependencies are satisfied.
- Because the flow ops reused scratch registers (`vec_addr`, `vec_val_save`, `vec_node_val`) that were also used by VALU ops in the same group, the scheduler likely moved the flow selects earlier than intended, before their inputs were fully computed.

This matches a prior pitfall documented in `6_optimization_summary.md`: flow‑based selection is sensitive to data dependencies and register reuse.

**Result:** Reverted to the VALU arithmetic selection to restore correctness.

---

## Tests and outcomes

- `python tests/submission_tests.py`
  - With the flow‑select attempt: **correctness failed** (all tests failed).
  - After reverting: **8/9 tests pass**, cycle count back to **1486**.

---

## Pitfalls / bugs encountered

1) **Scheduler reordering broke data dependencies**
   - Flow engine ops were scheduled before their inputs were valid due to weakly‑enforced dependencies caused by register reuse.
   - Lesson: flow‑based select needs explicit dependency anchoring or dedicated scratch regs that are not reused by concurrent VALU ops.

2) **Quick failure in debug mode**
   - Debug trace showed mismatched node values at round 0, depth 0—meaning the reordering caused unintended interference well beyond the modified depth‑2 path.

---

## Thoughts / conclusions

The kernel is still **VALU‑bound (~94%)**, but replacing VALU work with flow ops is risky because the flow engine has only 1 slot and because the scheduler does not guarantee ordering unless the dependency graph is explicit.

To use flow‑based selection safely, we likely need:
- **Dedicated scratch registers** for flow inputs/outputs (avoid aliasing with VALU temporaries).
- **Artificial dependency anchors** (e.g., dummy ALU/VALU ops or forced barriers) so the scheduler can’t reorder selects above their data producers.

---

## Research consulted (in this attempt)

No new web research was conducted during this attempt. I relied on existing research notes from prior optimization reports for guiding ideas (see below).

---

## Additional research‑driven ideas (future work)

These are carried forward from prior reports and still look promising:

1) **SIMTree‑style lane bucketization**
   - Group lanes by low bits of `idx` to increase SIMD coherence and reduce divergence.

2) **Top‑subtree scratch cache (RapidScorer‑style compactness)**
   - Cache a larger prefix of tree nodes in scratch and replace gathers with scratch reads for additional depths.

3) **Explicit scratch allocation pass (Register‑Your‑Forests idea)**
   - Systematically break false WAW/WAR chains and reduce artificial dependencies, possibly freeing scheduling latitude.

4) **Depth‑3 selection with dependency anchoring**
   - If selection can be isolated (extra scratch + forced order), this could remove another gather round.

---

## Files touched

- `perf_takehome.py` (temporary change, reverted)
- `docs/reports/optimizations/7_optimization_summary.md` (this report)
