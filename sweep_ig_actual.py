#!/usr/bin/env python3
"""Sweep interleave groups with actual defaults."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test

best_cycles = 1375
results = []

# Try wider range
for ig in range(8, 40):
    for ige in range(8, 40):
        kwargs = {
            'scheduler_random_seed': 202,
            'scheduler_crit_weight': 200,
            'scheduler_succ_weight': 2500,
            'scheduler_beam_width': 1,
            'interleave_groups': ig,
            'interleave_groups_early': ige,
            'split_hash_pairs': True,
        }
        try:
            cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
            results.append((cycles, ig, ige))
            if cycles < best_cycles:
                best_cycles = cycles
                print(f"*** NEW BEST: ig={ig}, ige={ige}, cycles={cycles} ***")
        except Exception:
            pass

results.sort()
print(f"\n=== TOP 20 ===")
for cycles, ig, ige in results[:20]:
    print(f"  ig={ig}, ige={ige}: {cycles}")
print(f"\nBest: {best_cycles}")
