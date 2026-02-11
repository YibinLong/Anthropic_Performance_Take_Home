#!/usr/bin/env python3
"""Sweep interleave_groups and interleave_groups_early."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test

baseline_kwargs = {
    'scheduler_random_seed': 202,
    'scheduler_crit_weight': 220,
    'scheduler_succ_weight': 5120,
    'scheduler_beam_width': 1,
    'split_hash_pairs': True,
}

results = []
best_cycles = 1382

for ig in range(16, 33):
    for ige in range(16, 33):
        kwargs = dict(baseline_kwargs)
        kwargs['interleave_groups'] = ig
        kwargs['interleave_groups_early'] = ige
        try:
            cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
            results.append((cycles, ig, ige))
            if cycles < best_cycles:
                best_cycles = cycles
                print(f"*** NEW BEST: ig={ig}, ige={ige}, cycles={cycles} ***")
        except Exception as e:
            pass  # Silently skip failures (scratch space overflow)

results.sort()
print("\n\n=== TOP 20 INTERLEAVE COMBOS ===")
for cycles, ig, ige in results[:20]:
    print(f"  ig={ig}, ige={ige}: {cycles} cycles")
print(f"\nBest: cycles={best_cycles}")
