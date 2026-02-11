#!/usr/bin/env python3
"""Broad sweep of scheduler_random_seed from 0 to 500."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test

baseline_kwargs = {
    'scheduler_crit_weight': 220,
    'scheduler_succ_weight': 5120,
    'scheduler_beam_width': 1,
    'interleave_groups': 25,
    'interleave_groups_early': 29,
    'split_hash_pairs': True,
}

results = []
best_cycles = 1382
best_seed = 202

for seed in range(0, 501):
    kwargs = dict(baseline_kwargs)
    kwargs['scheduler_random_seed'] = seed
    try:
        cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
        results.append((cycles, seed))
        if cycles < best_cycles:
            best_cycles = cycles
            best_seed = seed
            print(f"*** NEW BEST: seed={seed}, cycles={cycles} ***")
    except Exception as e:
        print(f"seed={seed} failed: {e}")

results.sort()
print("\n\n=== TOP 30 SEEDS ===")
for cycles, seed in results[:30]:
    print(f"  seed={seed}: {cycles} cycles")
print(f"\nBest: seed={best_seed}, cycles={best_cycles}")
