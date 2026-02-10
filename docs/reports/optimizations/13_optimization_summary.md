# Optimization Session Report: Depth-3 Compact-State Exploration (No Net Gain)

## Summary (2026-02-10)

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Cycle count | 1446 | 1446 | 0 (no net gain) |
| Speedup over baseline | 102.17x | 102.17x | 0 |
| Tests passing (`tests/submission_tests.py`) | 8/9 | 8/9 | no change |

Remaining failure is unchanged:
- `test_opus45_improved_harness` (`< 1363`)

This session attempted a substantial depth-3 optimization, validated it, and then reverted it because it regressed cycles.

---

## Context

Starting point was the current best documented kernel state:
- `docs/reports/optimizations/00_optimization_landscape.md`
- `docs/reports/optimizations/8_optimization_summary.md`
- `docs/reports/optimizations/9_optimization_summary.md`
- `docs/reports/optimizations/10_optimization_summary.md`
- `docs/reports/optimizations/11_optimization_summary.md`
- `docs/reports/optimizations/12_optimization_summary.md`

Baseline verification:

```bash
python tests/submission_tests.py
python -m tools.opt_debug.run_diagnostics
```

Baseline diagnostics were consistent with previous sessions:
- `valu` ~92.5% utilization
- `load` ~91.7% utilization
- `flow` saturated in ~35% of cycles

---

## Hypothesis (Most Likely to Succeed)

The most plausible next step was:

1. Extend compact traversal state one level deeper (through depth 3).
2. Replace depth-3 gathers (`idx in [7..14]`) with branchless local selection from preloaded node constants.
3. Trade some `flow/valu` work to materially reduce `load` pressure.

Rationale:
- Kernel remained dual-bottlenecked (`valu` + `load`).
- Prior improvements proved early-depth gather elimination can produce meaningful wins.
- Depth-3 is the next deterministic top-of-tree region.

---

## What I Implemented (Attempt)

All attempted kernel edits were in `perf_takehome.py` (later reverted).

### 1) Added depth-3 compact mode

- Gated mode for submission path and scratch-safe interleave settings.
- Temporarily moved `interleave_groups_early` default from 29 to 26 to recover scratch headroom for new vectors.

### 2) Preloaded depth-3 nodes 7..14

- Added scalar loads for nodes `7..14`.
- Broadcast those nodes to vector constants (`vec_node7..vec_node14`).

### 3) Added branchless depth-3 selection path

- Computed `path = idx - 7`.
- Built an 8-way selection tree using path bits and `flow.vselect`.
- Reused compact state transitions so gather was skipped at depth 3.

### 4) Added dedicated condition temporaries after debugging

- Initial implementation reused condition temporaries and produced correctness failures.
- Fixed by allocating dedicated vectors for selection conditions (`b2`, `b1`, `b0`) to prevent scheduler WAR hazards.

---

## Debugging Process and Findings

Initial result of the new path:
- Incorrect output values in submission mode.
- Full suite failed.

Debugging workflow:

```bash
python tests/submission_tests.py
python -m tools.opt_debug.run_diagnostics
python - <<'PY'
# targeted micro-runs over small rounds/batch to find earliest failing round
PY
```

Key findings:
- Earliest failures showed incorrect node selection in depth-3 round behavior.
- Trace inspection showed condition temporaries being reused in ways that scheduler WAR handling could reorder unsafely.
- This class of issue matched known prior guardrails: flow-select logic is fragile under register reuse.

Fix status:
- Correctness issue was fixed by introducing non-overlapping condition temporaries and avoiding aliasing in the selection tree.
- After that fix, correctness passed for both small targeted runs and full submission correctness checks.

---

## Why It Still Failed to Improve Cycles

Even with correctness fixed, performance regressed badly.

Observed best for the attempted depth-3 variant:
- ~`1681` cycles (correct), far worse than `1446`.

Main reasons:

1. **Flow pressure explosion**
- Depth-3 select tree added many `flow.vselect` operations in a region where flow was already non-trivial.
- `flow` has only 1 slot/cycle, so this quickly became a hard bottleneck.

2. **Scratch pressure and interleave compromise**
- Additional node vectors and condition temporaries increased scratch usage significantly.
- Needed lower early interleave (26 instead of 29), which hurt throughput.

3. **Extra setup overhead**
- New node preload/broadcast/header work added up-front cost that did not amortize enough.

Net: reduced gather loads did not offset increased flow serialization + reduced interleave capacity.

---

## Parameter Search Results

After the failed structural attempt, I ran an additional focused config search on the baseline-safe kernel shape (no retained logic change), including interleave and scheduler bias variants.

Outcome:
- No config beat `1446`.
- Best found in sampled sweep tied current best (`1446`) with an alternate scheduler-weight/bias tuple.

This reinforces that current retained kernel is still at a local optimum for tested knobs.

---

## Research Consulted

Parallel research was done to guide the attempt, especially on:
- compact traversal state
- branchless small-set selection
- VLIW software-pipelining safety for address/dependency handling

Primary sources reviewed:

```text
QuickScorer:
https://arpi.unipi.it/handle/11568/945058

FastBDT:
https://arxiv.org/abs/1609.06119

CatBoost/oblivious tree evaluation:
https://arxiv.org/abs/2211.00391

MatrixNet/CatBoost SIMD binarization framing:
https://arxiv.org/abs/2205.07307

Quantization/compact inference framing:
https://arxiv.org/abs/2305.08579

Modulo scheduling legality / constraints:
https://www.osti.gov/biblio/274236
```

How research influenced conclusions:
- Supported trying compact top-depth state before riskier pointer/address rewrites.
- Emphasized that branchless select trees must respect dependency/legal-schedule constraints.
- Helped explain why the added flow-heavy implementation regressed on this ISA.

---

## Bugs / Pitfalls Encountered

1. **Depth-3 flow-select correctness bug**
- Cause: condition/register reuse + scheduler ordering interactions.
- Status: fixed with dedicated condition vectors and stricter dependency separation.

2. **Large cycle regression despite correctness**
- Cause: flow-slot saturation + reduced interleave due scratch pressure.
- Status: unresolved for this approach; optimization reverted.

3. **High invalid region in attempted parameter space**
- Some interleave/settings around the modified kernel either regressed heavily or became invalid.
- Status: avoided by reverting to known-safe baseline.

---

## Final Conclusion

The attempted depth-3 compact-selection optimization was **technically implementable and debuggable for correctness**, but it is **not viable** in current form due to substantial cycle regression.

Final retained state was intentionally reverted to preserve non-regressed performance:
- **`1446` cycles**
- **`8/9` submission tests passing**

---

## Handoff: What To Try Next

1. Depth-3 strategy with lower flow usage:
- Explore VALU-centric 8-way selection (bitwise one-hot/mux arithmetic) to avoid flow-slot bottleneck.

2. Recover scratch headroom without lowering interleave:
- Reduce per-group temporary footprint or phase-split allocations so `interleave_groups_early=29` can be preserved.

3. Hybrid depth-3 approach:
- Partial cache/select only where it minimizes total added ops; avoid full 8-way select tree for all lanes.

4. Strengthen auto-search constraints:
- Add explicit scratch/correctness guardrails to avoid wasting trials in known-unsafe regions.

---

## Validation Commands (Final Retained State)

```bash
python perf_takehome.py
python tests/submission_tests.py
python -m tools.opt_debug.run_diagnostics
```

Expected retained result:
- `CYCLES: 1446`
- same single threshold failure at `< 1363`

