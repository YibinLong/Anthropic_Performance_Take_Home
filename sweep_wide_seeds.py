#!/usr/bin/env python3
"""Wide seed sweep 1000-10000 with current defaults."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test

best_cycles = 1375
best_seed = 202

for seed in range(1001, 10001):
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
    if cycles < best_cycles:
        best_cycles = cycles
        best_seed = seed
        print(f"*** NEW BEST: seed={seed}, cycles={cycles} ***")
    if seed % 1000 == 0:
        print(f"Progress: seed={seed}, best={best_cycles}")

print(f"\nBest: seed={best_seed}, cycles={best_cycles}")
