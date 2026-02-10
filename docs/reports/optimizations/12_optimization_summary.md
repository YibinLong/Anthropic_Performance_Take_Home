# Optimization Session Report: Critical-Path Exploration Without Net Gain (2026-02-10)

## Summary

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Cycle count | 1446 | 1446 | 0 |
| Speedup over baseline | 102.17x | 102.17x | 0 |
| Tests passing (`tests/submission_tests.py`) | 8/9 | 8/9 | no change |

Remaining failure:
- `test_opus45_improved_harness` (`< 1363`) still fails at **1446** cycles.

This session produced no retained kernel changes; all regressive or incorrect experiments were reverted.

---

## Context and Goal

Starting point was the state from:
- `docs/reports/optimizations/00_optimization_landscape.md`
- `docs/reports/optimizations/8_optimization_summary.md`
- `docs/reports/optimizations/9_optimization_summary.md`
- `docs/reports/optimizations/10_optimization_summary.md`
- `docs/reports/optimizations/11_optimization_summary.md`

The objective was to scrutinize the implementation line-by-line, use diagnostics + external research, form the highest-confidence optimization hypothesis, implement it, and validate with the full test suite while avoiding regressions.

---

## Baseline and Diagnostics

Baseline commands:

```bash
python tests/submission_tests.py
python -m tools.opt_debug.run_diagnostics
```

Confirmed baseline:
- Cycles: **1446**
- Correctness: pass on value checks (8/9 thresholds due to final strict target)

Diagnostics indicated:
- `valu` utilization: ~92.5%
- `load` utilization: ~91.7%
- `flow` saturated ~35.4% of cycles
- Critical path starts were dominated by early load/address setup chains.

---

## Primary Hypothesis (Most Likely to Succeed)

### Hypothesis
Reduce critical-path address setup serialization in vector prelude/epilogue (especially chains through `tmp_addr_b`) by precomputing stable vector value addresses once and reusing them for `vload`/`vstore`.

### Why this seemed likely
1. The hottest critical-path entries repeatedly involved address-gen + load adjacency.
2. It targeted setup overhead without changing hash/tree arithmetic.
3. It followed prior “running pointer” intuition but attempted a safer precomputed-address variant.

---

## Experiments Performed

## 1) Submission-path vector address precompute/reuse

### What was changed
- Added precomputed per-vector value addresses in submission mode.
- Reused those addresses for both value prelude loads and value epilogue stores.

### Result
- **Incorrect output values** (correctness regression).
- Diagnostics run also showed worse cycles in failing variant (~1604).

### Conclusion
- Reverted fully.
- Inference: this introduced schedule-sensitive hazards in address/data dependencies under VLIW reordering.

---

## 2) Depth-3-specific interleave width knob

### What was changed
- Temporarily added `interleave_groups_depth3` so depth 3 could use a different group count than depths `<=2` and `>=4`.

### Result
- Sweeps showed no better result than baseline.
- Best remained equivalent to baseline behavior (effectively `1446` at existing setting).

### Conclusion
- Reverted the knob to keep kernel simpler.

---

## 3) Depth-2 compact idx materialization VALU->FLOW trade

### What was changed
- Replaced `+ b2` in compact depth-2 idx materialization with a `flow.vselect` between constants `7` and `8`, then one `multiply_add`.

### Result
- Correctness preserved.
- Cycles regressed to **1447**.

### Conclusion
- Reverted. Flow pressure increase outweighed VALU reduction.

---

## 4) Tail partial-chunk register remap

### What was changed
- For partial vector chunks, remapped to use later group registers first.

### Result
- Correctness preserved.
- Large regression to **1583** cycles.

### Conclusion
- Reverted immediately.

---

## 5) Scheduler tie-break by slot width

### What was changed
- Modified ready-queue priority tie-break to prefer larger slot-count ops.

### Result
- Correctness preserved.
- Cycles regressed to **1447**.

### Conclusion
- Reverted.

---

## 6) Parameter sweeps (config-only search)

Performed multiple sweeps:
- Focused interleave sweeps around current optimum.
- Broad randomized sweeps (hundreds of trials) across:
  - `interleave_groups`, `interleave_groups_early`
  - `depth2_select_mode`, `idx_branch_mode`
  - `scheduler_crit_weight`, engine biases

Outcome:
- No valid configuration beat **1446**.
- Configs with `interleave_groups_early >= 30` frequently produced incorrect outputs.

---

## Research Consulted and How It Informed Decisions

Sources used:

```text
RapidScorer (KDD 2018):
https://www.kdd.org/kdd2018/accepted-papers/view/rapidscorer-fast-tree-ensemble-evaluation-by-maximizing-compactness-in-data

Register Your Forests:
https://arxiv.org/abs/2404.06846

FastBDT:
https://arxiv.org/abs/1609.06119

TI Software Pipelining and Addressing Notes:
https://downloads.ti.com/docs/esd/SPRUI04/optimizing-software-pipelining-spru1875784.html
https://downloads.ti.com/docs/esd/SPRU514/convert-array-references-in-loops-to-incremented-pointer-form-spru1871785.html
```

How this influenced this session:
- Reinforced prioritizing compactness and dead-work/address-traffic reduction once obvious arithmetic rewrites plateau.
- Supported testing schedule/packing changes before high-risk deeper traversal rewrites.
- Also highlighted that aggressive address-form rewrites can be fragile under reordering unless dependency anchoring is explicit.

---

## Bugs / Pitfalls Encountered

1. **Address precompute rewrite broke correctness**
- Status: reproduced, diagnosed as scheduling/dependency hazard class, and fully reverted.

2. **High early interleave (`>=30`) often invalid**
- Status: reproducibly incorrect on current kernel shape; treated as unsafe region.

3. **“Looks-good” cycle points in search can be invalid if correctness fails**
- Status: search runs always re-checked against reference values; invalid points were discarded.

All encountered issues in retained code were resolved via revert; final repository state is correct and baseline-equivalent.

---

## Final Conclusion

For this session, the kernel appears to be at a local optimum around **1446 cycles** under current architecture constraints and current safe transformation set.

No safe net improvement was found after:
- structural address-path experimentation,
- scheduler-order experimentation,
- and broad parameter sweeps.

---

## Handoff Guidance for Future Agents

Highest-value next directions:
1. **Depth-3 gather reduction with explicit dependency anchoring**
- Try a narrow, correctness-first transformation with non-aliasing temporaries and stronger ordering constraints.

2. **Address-sensitive transform with explicit barriers/anchoring**
- If revisiting pointer/address optimizations, add hard dependency anchors or segmented scheduling around those regions.

3. **Scratch-aware, correctness-first auto-search**
- Keep rejecting configs that cross into known-unsafe interleave regions or scratch-pressure edges.

4. **Upper-subtree selective caching (not full rewrite)**
- Try partial cache of depth-3/4 nodes only if load reduction clearly outweighs added flow/valu pressure and scratch cost.

Repro commands:

```bash
python tests/submission_tests.py
python -m tools.opt_debug.run_diagnostics
```

