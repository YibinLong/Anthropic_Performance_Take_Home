# Optimization Session Report: Compact Early-Depth Index State (2026-02-10)

## Summary

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Cycle count | 1474 | 1453 | -21 (-1.42%) |
| Speedup over baseline | 100.23x | 101.68x | +1.45x |
| Tests passing (`tests/submission_tests.py`) | 8/9 | 8/9 | no change |

Remaining failure:
- `test_opus45_improved_harness` (`< 1363`) still fails, now at **1453**.

---

## Objective and Context

This continued from:
- `docs/reports/optimizations/00_optimization_landscape.md`
- `docs/reports/optimizations/8_optimization_summary.md`
- `docs/reports/optimizations/9_optimization_summary.md`

Starting point was a correct submission kernel at **1474 cycles** after non-debug index memory traffic elimination.

The diagnostic profile at this point remained heavily constrained by:
- VALU utilization around 93%
- LOAD utilization around 90%
- FLOW moderate (~35%) but not dominant

---

## Hypothesis (Most Likely to Succeed)

The highest-confidence next optimization was to reduce early-round index arithmetic, not by another risky depth-3 gather rewrite, but by changing what state is carried in `idx` for depths `0..2` in submission mode:

- carry compact path bits across the first 3 depths,
- avoid repeatedly materializing full tree index during those rounds,
- reconstruct full `idx` once at the depth-2 boundary before depth-3 gathers.

Why this was likely:
1. It directly removes hot-path VALU work in a phase repeated for all lanes.
2. It avoids previously regressive patterns (weakly anchored depth-3 rewrites, fragile vselect tree rewrites).
3. It is compatible with submission-mode semantics and existing correctness checks.

---

## What I Changed

All code changes are in `perf_takehome.py`.

### 1) Added compact early-depth mode (submission path only)

Introduced:
- `use_compact_depth_state = (not self.emit_debug and self.depth2_select_mode == "flow_vselect")`

This keeps debug behavior untouched and only applies to the stable flow-vselect path.

Code location:
- `perf_takehome.py:1013`

### 2) Added constant needed for compact idx reconstruction

Added:
- `vec_seven = alloc_vec_const(7, "vec_seven")`

Used for reconstructing full idx at depth 2:
- `idx = 7 + 2*path + b2`

Code location:
- `perf_takehome.py:895`

### 3) Rewrote depth-1 node selection under compact mode

Old depth-1 path used arithmetic blend from full `idx`.

New compact depth-1 path:
- depth-0 stores `b0` (`val & 1`) in `vec_idx`
- depth-1 node value selected directly:
  - `flow.vselect(vec_node_val, vec_idx, vec_node2, vec_node1)`

Code location:
- `perf_takehome.py:1058`

### 4) Rewrote depth-2 node selection under compact mode

At depth-2, compact `vec_idx` carries `path = 2*b0 + b1` (range `[0,3]`):
- extract low/high bits with cheap bitwise ops
- use flow selects to pick among `{node3,node4,node5,node6}`

Code location:
- `perf_takehome.py:1086`

### 5) Replaced early idx update chain with compact transitions

In compact mode:
- depth 0: `vec_idx = b0`
- depth 1: `vec_idx = 2*b0 + b1`
- depth 2: `vec_idx = 7 + 2*(2*b0+b1) + b2` (materialize full idx for depth 3+)

Code location:
- `perf_takehome.py:1177`

### 6) Retuned early interleave groups for the new kernel shape

After structural changes, retuned interleave settings and found:
- `interleave_groups = 25` (unchanged)
- `interleave_groups_early = 28` (was `26`)

Updated default:
- `interleave_groups_early: int | None = 28`

Code location:
- `perf_takehome.py:272`

---

## Thought Process and How I Reached This

### Step 1: Reconfirm baseline and pressure

Ran:
- `python tests/submission_tests.py`
- `python -m tools.opt_debug.run_diagnostics`

Confirmed:
- baseline `1474`
- still dual-bottlenecked (VALU + LOAD).

### Step 2: Exhaust parameter-only headroom first

Before touching logic, ran broad sweeps over existing knobs:
- `interleave_groups`, `interleave_groups_early`
- `depth2_select_mode`, `idx_branch_mode`
- scheduler critical-path weight and engine biases

Result:
- no parameter-only configuration beat `1474` pre-change.

Conclusion:
- needed a semantic/kernel-structure change, not another scheduling tweak.

### Step 3: Line-by-line implementation scrutiny

The repeated depth `0..2` logic revealed consistent idx work that could be compressed:
- full idx math done each round,
- then only partial branch/path bits needed immediately after,
- full idx only truly required once depth-3 gathers start.

This aligned with the compact traversal ideas from prior research.

### Step 4: Implement safest structural change

Applied compact mode only when:
- `emit_debug=False` (submission fast path)
- `depth2_select_mode="flow_vselect"` (known-correct path)

Preserved debug path and fallback logic to minimize regression risk.

### Step 5: Retune after structural shift

As expected, changing VALU/FLOW mix shifted best interleave point:
- new best at `interleave_groups_early=28`.

---

## Experiments Explored (What Worked / Didn’t)

1. Pre-change config sweeps (196 configs around current shape)
- Outcome: best remained `1474`.

2. Pre-change scheduler bias sweep (600 configs)
- Outcome: best remained `1474`.

3. Compact early-depth state implementation
- Outcome: immediate improvement to `1454`.

4. Post-change interleave retune
- Outcome: improved further to `1453` at `(25, 28)`.

5. Post-change scheduler bias sweep (600 configs)
- Outcome: no improvement over `1453`.

---

## Pitfalls / Bugs Encountered

1. **Diagnostic-tool default mismatch**
- `tools.opt_debug.run_diagnostics` still defaults to `interleave_groups_early=26`.
- Running diagnostics without overriding this showed `1454`, while submission tests (using `KernelBuilder()` defaults) showed `1453`.
- Status: worked around by passing `--interleave-groups-early 28` when collecting diagnostics. Tool default itself was not updated in this session.

2. **Scratch budget pressure**
- New constant and logic increased scratch usage to `1507 / 1536`.
- No overflow occurred, but headroom is smaller now.
- Status: acceptable, but future work should track scratch growth carefully.

3. **No correctness regressions**
- Debug behavior intentionally preserved.
- Submission correctness unchanged.

---

## Validation Performed

Commands run:

```bash
python tests/submission_tests.py
python perf_takehome.py
python -m tools.opt_debug.run_diagnostics --interleave-groups 25 --interleave-groups-early 28
```

Observed results:
- Submission cycles: **1453**
- Submission pass status: **8/9** (same single threshold failure)
- Local tests in `perf_takehome.py`: pass

---

## Research Consulted

RapidScorer (compactness / upper-tree optimization):
https://www.kdd.org/kdd2018/accepted-papers/view/rapidscorer-fast-tree-ensemble-evaluation-by-maximizing-compactness-in-data

SIMTree (SIMD traversal coherence / lane behavior ideas):
https://engineering.purdue.edu/plcl/simtree/

FastBDT (branchless / cache-aware tree execution framing):
https://arxiv.org/abs/1609.06119

Register Your Forests (register/scratch pressure and allocation viewpoint):
https://arxiv.org/abs/2404.06846

QuickScorer (compact traversal state ideas):
https://arpi.unipi.it/handle/11568/945058

How research informed this session:
- reinforced that compact traversal state is often a better next step than deeper random scheduling tweaks once low-level tuning plateaus.
- supported prioritizing low-risk state compression over high-risk depth-3 gather rewrites.

---

## Next Ideas for Future Agents

1. Extend compact-state idea into depth-3 with strict dependency anchoring
- Candidate: carry a 3-bit path state and select from a cached top subtree.
- Risk: flow-slot saturation and scratch pressure.

2. Hybrid depth-3 optimization (partial cache + reduced gathers)
- Cache only a subset of depth-3 nodes where it gives best load/flow tradeoff.
- Compare against pure gather path with diagnostics.

3. Make diagnostic/optimizer defaults consistent with kernel defaults
- Update tooling defaults (`interleave_groups_early`) to avoid misleading diagnostics.

4. Add scratch-aware constraints to auto-search
- Reject configs near overflow before full kernel build.

5. Investigate phase-specific interleave policy
- Early depths are now structurally different from later gather-heavy depths; dynamic group choices per depth bucket may still unlock small gains.

