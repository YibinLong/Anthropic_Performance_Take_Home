# Optimization Landscape Summary (for future agents) 

NOTE: This is for Optimization Summaries 1-7 ONLY

Purpose: provide a high-signal map of what's already been tried, what worked, what didn't, and where the remaining headroom likely is. Each bullet cites the original report so you can dive deeper.

## Current best known state (as of 2026-02-05)

- **Cycle count:** 1486; **tests passing:** 8/9; only remaining failure is `< 1363` in `test_opus45_improved_harness`. This result came after moving branch selection to the flow engine and retuning interleave groups. [source: docs/reports/optimizations/6_optimization_summary.md]
- **Interleave tuning:** best observed split is `interleave_groups=25` and `interleave_groups_early=26` for the current kernel shape. [source: docs/reports/optimizations/6_optimization_summary.md]
- **Most recent attempt reverted:** replacing depth-2 arithmetic selection with flow `vselect` broke correctness and was fully reverted; final state remains 1486 cycles. [source: docs/reports/optimizations/7_optimization_summary.md]

## Core constraints and kernel shape (stable context)

- **Architectural constraints that drive scheduling:** VLIW slot limits per cycle (ALU 12, VALU 6, Load 2, Store 2, Flow 1), static scratch addressing, writes commit at end of cycle, and `vload/vstore` only for contiguous regions. These facts are essential for hazard reasoning and explain why some reorderings break correctness. [source: docs/reports/optimizations/1_optimization_summary.md]
- **Kernel structure (high-level):** unrolled rounds in Python, SIMD vector path with `load_offset` gathers, scratch-resident `idx/val` arrays loaded once in the prelude and stored once in the epilogue, plus a scalar tail for non-multiple-of-VLEN. This remains the baseline shape that later optimizations build on. [source: docs/reports/optimizations/1_optimization_summary.md]

## Major wins and the path to 1486 cycles

- **Foundation:** implemented a real dependency-aware VLIW scheduler, SIMD hash, multi-group interleaving, constant dedupe, and DCE; the biggest early win was keeping the entire batch in scratch across rounds (Task 16), which dropped cycles to 2177 before later algorithmic changes. [source: docs/reports/optimizations/1_optimization_summary.md]
- **Header + prelude scheduling & load packing:** moved header/const loads into the VLIW body, eliminated single-slot load cycles from `self.add()`, and broke WAW chains with extra temps; this reduced cycles from 2177 -> 2123 and exposed the load-bound floor. [source: docs/reports/optimizations/2_optimization_summary.md]
- **Depth-aware gather elimination (depths 0-2):** computed node values from preloaded constants for early depths, removed gathers for those rounds, and gated wrap checks to depth==height. This cut cycles from 2123 -> 1764 and shifted the bottleneck to VALU. [source: docs/reports/optimizations/3_optimization_summary.md]
- **Interleave group retune (VALU-bound phase):** grid search found `interleave_groups=26` best for the new VALU-heavy schedule, improving to 1566 cycles. [source: docs/reports/optimizations/4_optimization_summary.md]
- **Depth-1/2 VALU algebraic reductions:** algebraic rewrites removed VALU ops in depth-1 and depth-2 selection, improving 1563 -> 1547 cycles. [source: docs/reports/optimizations/5_optimization_summary.md]
- **Flow-engine branch select:** replaced `(val & 1) + 1` with `flow.vselect` (offloading VALU), then retuned interleave groups to 25/26; final 1547 -> 1486 cycles. [source: docs/reports/optimizations/6_optimization_summary.md]

## Things that did NOT help (or regressed)

- **Root node cache in scratch regressed** (2177 -> 2351) and was rolled back. [source: docs/reports/optimizations/1_optimization_summary.md]
- **Critical-path scheduler priority** produced no gain once the load engine was ~99% saturated. [source: docs/reports/optimizations/2_optimization_summary.md]
- **Depth-3 arithmetic selection** (nodes 7..14) was incorrect under scheduling and reverted. [source: docs/reports/optimizations/4_optimization_summary.md]
- **Running pointer prelude/epilogue** to remove offset const loads broke correctness (dependency reordering). [source: docs/reports/optimizations/4_optimization_summary.md]
- **Flow-based depth-2 selection** via `vselect` broke correctness due to scheduling/reuse hazards; reverted. [source: docs/reports/optimizations/7_optimization_summary.md]

## Bottleneck evolution (important for next moves)

- **Pre-depth-aware phase:** kernel was load-bound; theoretical floor dictated by 4096 gathers at 2 loads/cycle, so rescheduling alone could not hit <1790 without reducing gathers. [source: docs/reports/optimizations/2_optimization_summary.md]
- **Post depth-aware gather elimination:** kernel became **VALU-bound**, and interleave-group tuning became the dominant lever. [source: docs/reports/optimizations/4_optimization_summary.md]
- **Current state:** still largely VALU-bound; flow engine is lightly used and can sometimes offload tiny pieces (branch select). [source: docs/reports/optimizations/6_optimization_summary.md]

## Documented future directions (from prior reports)

- **Extend depth-aware selection (depth 3/4) with stronger dependency anchoring** or a small LUT, to remove additional gather rounds without scheduling hazards. [source: docs/reports/optimizations/4_optimization_summary.md]
- **Top-subtree scratch cache** (RapidScorer-inspired) to replace gathers for upper depths; needs careful scratch budgeting. [source: docs/reports/optimizations/4_optimization_summary.md]
- **Lane bucketization / traversal splicing** (SIMTree-style) to improve SIMD coherence and reduce VALU pressure. [source: docs/reports/optimizations/6_optimization_summary.md]
- **Explicit scratch allocation / dependency anchoring** to avoid reordering issues when using flow-engine selects. [source: docs/reports/optimizations/7_optimization_summary.md]

## Quick don't repeat this checklist

- Don't emit hot-path ops via `self.add()` unless they truly must be unscheduled; it creates single-slot cycles. [source: docs/reports/optimizations/2_optimization_summary.md]
- Don't split header/body into separate VLIW segments unless you also protect against DCE removing header-only writes. [source: docs/reports/optimizations/2_optimization_summary.md]
- Be careful with flow-engine `vselect` and register reuse; scheduler reordering can break correctness. [source: docs/reports/optimizations/7_optimization_summary.md]
- Always retune `interleave_groups` after changing the VALU/load balance. [source: docs/reports/optimizations/4_optimization_summary.md]
