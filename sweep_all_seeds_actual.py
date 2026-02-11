#!/usr/bin/env python3
"""Sweep seeds 0-1000 with actual current defaults (cw=200, sw=2500)."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test

best_cycles = 1375
best_seed = 202
results = []

for seed in range(0, 1001):
    kwargs = {
        'scheduler_random_seed': seed,
        'scheduler_crit_weight': 200,
        'scheduler_succ_weight': 2500,
        'scheduler_beam_width': 1,
        'interleave_groups': 25,
        'interleave_groups_early': 29,
        'split_hash_pairs': True,
    }
    cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
    results.append((cycles, seed))
    if cycles < best_cycles:
        best_cycles = cycles
        best_seed = seed
        print(f"*** NEW BEST: seed={seed}, cycles={cycles} ***")

results.sort()
print(f"\n=== TOP 30 ===")
for cycles, seed in results[:30]:
    print(f"  seed={seed}: {cycles}")
print(f"\nBest: seed={best_seed}, cycles={best_cycles}")
