#!/usr/bin/env python3
"""Sweep seeds x interleave groups together."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test

best_cycles = 1375
results = []

# Seeds that gave 1375
good_seeds = [15, 61, 63, 154, 168, 202, 220, 244, 274, 275, 278, 284, 287, 291, 295, 330, 349, 357, 410, 433, 459, 468]

# Try interleave groups around best
for seed in good_seeds:
    for ig in range(22, 30):
        for ige in range(26, 32):
            kwargs = {
                'scheduler_random_seed': seed,
                'scheduler_crit_weight': 200,
                'scheduler_succ_weight': 2500,
                'scheduler_beam_width': 1,
                'interleave_groups': ig,
                'interleave_groups_early': ige,
                'split_hash_pairs': True,
            }
            try:
                cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
                if cycles <= 1375:
                    results.append((cycles, seed, ig, ige))
                if cycles < best_cycles:
                    best_cycles = cycles
                    print(f"*** NEW BEST: seed={seed}, ig={ig}, ige={ige}, cycles={cycles} ***")
            except Exception:
                pass

results.sort()
print(f"\n=== ALL <= 1375 ===")
for entry in results[:50]:
    print(f"  {entry}")
print(f"\nBest: {best_cycles}")
