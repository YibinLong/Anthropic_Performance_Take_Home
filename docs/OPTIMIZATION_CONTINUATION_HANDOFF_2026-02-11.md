# Optimization Continuation Handoff (2026-02-11)

## Snapshot
- Date: 2026-02-11
- Repo commit during this pass: `0baaa32f0937bf8e2b2349cc7ff4459cff2ecd11`
- File under optimization: `perf_takehome.py`
- Guardrails:
  - `tests/` unchanged (`git diff -- tests/` stayed empty)
  - Validation command: `python tests/submission_tests.py`
- Current measured state:
  - Correctness: pass
  - Speed tests: `8/9` pass
  - Cycles: `1407`
  - Failing threshold: `<1363` (gap: 44 cycles)

## Repro Baseline
Run this first in every continuation session:

```bash
git diff -- tests/
python tests/submission_tests.py
```

Expected today:
- `tests/` diff is empty
- `CYCLES: 1407`

## Diagnostics Taken
Ran:

```bash
python tools/opt_debug/run_inefficiency_report.py --out-dir docs/reports/optimizations/debug
```

Key output from this pass:
- cycles: `1407`
- estimated_headroom_cycles: `79`
- top blockers:
  - `strict_dep_wait` (dominant)
  - `engine_full`
  - `weak_dep_wait` (small)

Interpretation:
- This kernel is still mostly dependency-limited, not tie-break-limited.
- Small scheduler-parameter changes are unlikely to recover 44 cycles alone.

## What Was Tried In This Pass

### 1. Scheduler/knob sweeps (no code changes)

| Attempt | Scope | Result |
|---|---|---|
| Constrained scheduler sweep | seeds + crit/succ weights + beam + multi-start + mode toggles (~1658 trials) | Best remained `1407` |
| Interleave grid | `interleave_groups` x `interleave_groups_early` | Best remained `1407` at `25/29` |
| Random cross-knob search | broad mixed-parameter samples | No `<1407` candidate found before cutoff |
| Seed-only sweep | `scheduler_random_seed` in large ranges (including up to 2500 via `len(kb.instrs)` proxy) | Best remained seed `51` with `1407` |
| High-range weight sweep | larger `scheduler_crit_weight`/`scheduler_succ_weight` ranges | Best was worse (`>=1412`) |

Conclusion:
- Current default scheduler knobs are at a local optimum for this code shape.

### 2. Code-level experiments (all reverted)

| Change tested | Observed result | Why rejected |
|---|---|---|
| Mixed 2-reg/3-reg group allocation (depth-aware) | No gain by itself | Increased schedule brittleness; no better packing found |
| Precompute/reuse value vector addresses across prologue+epilogue | Regressed hard (around `1529`, best tuned still much worse) | Added long-lived address dependencies and front-loaded overhead |
| Temp remap in vector hash (`vec_tmp1` using `vec_val_save`) | `1410` | Register lifetime interaction made schedule worse |
| Skip unused `hash_c3` vector constants in simplified hash stages | Scratch dropped (`1524 -> 1499`) but cycles regressed (`1415`, best retuned `1409`) | Better scratch footprint did not translate to better schedule shape |
| Alter flow side-effect logic in DCE | `1415` | DCE removed ops that were helping schedule structure, not just dead work |
| Scheduler prototype: engine knapsack packing / closure variants | Worse than baseline (`~1410+` best case) | Naive global packing harmed dependency timing vs current greedy heuristic |

### 3. Sub-agent work
- Explorer agents proposed:
  - stronger scheduler packing
  - dependency-chain mitigation on address temps
- A worker agent ran independent tuning/search and also ended at:
  - best cycles: `1407`
  - no safe improvement identified

## What Not To Retry As-Is
These were explicitly re-tested in this pass and should not be repeated unchanged:

1. Pure scheduler parameter sweeps (seed/weights/beam/multi-start only).
2. Straightforward value-address precompute/reuse in load+store prologue/epilogue.
3. Simple register remaps in hash temporaries without changing dependency graph.
4. Isolated scratch-footprint reduction assumptions ("fewer scratch words => fewer cycles").

## Why The Above Failed

1. The schedule is highly shape-sensitive:
   - Small instruction-order/lifetime shifts can move many ops and increase cycle count.
2. Dominant blocker is strict dependencies:
   - Reducing overhead ops alone did not break critical chains.
3. Lower scratch usage is not automatically a win:
   - It can change op placement in ways that reduce packing quality.
4. The current heuristic is already tuned to this exact op graph:
   - Alternative heuristics need structural graph changes to outperform it.

## Recommended Next Steps (For Future Agents)

### Priority 1: Structural dependency surgery (not knob tuning)
Goal: reduce strict dependency pressure at hot value/address paths.

Candidate directions:
1. **Round-local value buffering experiments**:
   - explore selective double-buffering for value vectors only where chain depth is worst
   - avoid full-round double buffer overhead
2. **Targeted dependency splitting at depth transitions**:
   - especially around depth 2 -> depth 3 materialization path
3. **Op-graph reshaping before scheduling**:
   - split multi-slot bundled ops into finer ops with optional co-schedule hints
   - only keep if cycle wins are repeatable

### Priority 2: Guided search with automatic reject
Build a tiny local search loop that:
1. mutates one transformation at a time,
2. runs correctness + cycle check,
3. auto-reverts on regression,
4. logs results in one JSON line per trial.

This avoids repeating broad manual sweeps that already saturated.

### Priority 3: Re-check inefficiency report after each structural change
Track:
1. `estimated_headroom_cycles`
2. `strict_dep_wait`
3. top scratch hotspots

Keep only changes that improve cycles and reduce dependency pressure.

## Minimal Continuation Checklist

1. Confirm clean baseline:
```bash
git diff -- tests/
python tests/submission_tests.py
```
2. Make one structural change in `perf_takehome.py`.
3. Re-run:
```bash
python tests/submission_tests.py
python tools/opt_debug/run_inefficiency_report.py --out-dir docs/reports/optimizations/debug
```
4. Record:
   - cycles
   - pass/fail
   - why change helped or regressed
5. Revert immediately if regression is not offset by clear diagnostic improvement.

## Bottom Line
This pass did not find a safe improvement below `1407`. The productive frontier is now structural dependency-graph changes, not additional parameter sweeps.
