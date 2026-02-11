#!/usr/bin/env python3
"""Targeted sweep to beat 1375 cycles."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test

best_cycles = 1375
best_config = None
results = []

# Current best defaults: cw=200, sw=2500, seed=202, ig=25, ige=29
# Sweep crit_weight very finely
print("=== Phase 1: Fine crit_weight with current defaults ===")
for cw in range(50, 600, 1):
    kwargs = {
        'scheduler_random_seed': 202,
        'scheduler_crit_weight': cw,
        'scheduler_succ_weight': 2500,
        'scheduler_beam_width': 1,
        'interleave_groups': 25,
        'interleave_groups_early': 29,
        'split_hash_pairs': True,
    }
    cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
    if cycles < best_cycles:
        best_cycles = cycles
        best_config = kwargs.copy()
        print(f"*** NEW BEST: cw={cw}, cycles={cycles} ***")
    if cycles <= 1375:
        results.append((cycles, f"seed=202,cw={cw},sw=2500"))

print(f"\nPhase 1 best: {best_cycles}")

# Sweep succ_weight finely
print("\n=== Phase 2: Fine succ_weight ===")
for sw in range(500, 8001, 10):
    kwargs = {
        'scheduler_random_seed': 202,
        'scheduler_crit_weight': 200,
        'scheduler_succ_weight': sw,
        'scheduler_beam_width': 1,
        'interleave_groups': 25,
        'interleave_groups_early': 29,
        'split_hash_pairs': True,
    }
    cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
    if cycles < best_cycles:
        best_cycles = cycles
        best_config = kwargs.copy()
        print(f"*** NEW BEST: sw={sw}, cycles={cycles} ***")
    if cycles <= 1375:
        results.append((cycles, f"seed=202,cw=200,sw={sw}"))

print(f"\nPhase 2 best: {best_cycles}")

results.sort()
print(f"\n=== ALL <= 1375 ===")
for entry in results:
    print(f"  {entry}")
print(f"\nBest: {best_cycles}, config={best_config}")
