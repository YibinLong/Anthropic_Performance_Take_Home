#!/usr/bin/env python3
"""Fine-grained weight sweep around best values found so far."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test

baseline_kwargs = {
    'scheduler_beam_width': 1,
    'interleave_groups': 25,
    'interleave_groups_early': 29,
    'split_hash_pairs': True,
}

results = []
best_cycles = 1382

# Focus on the promising regions for seed=202
print("=== Seed 202: Fine sweep around best configs ===")
for cw in range(50, 501, 5):
    for sw in [2000, 2500, 3000, 3500, 4000, 4500, 5000, 5120, 5500, 6000]:
        kwargs = dict(baseline_kwargs)
        kwargs['scheduler_random_seed'] = 202
        kwargs['scheduler_crit_weight'] = cw
        kwargs['scheduler_succ_weight'] = sw
        cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
        results.append((cycles, 202, cw, sw))
        if cycles < best_cycles:
            best_cycles = cycles
            print(f"*** NEW BEST: seed=202, cw={cw}, sw={sw}, cycles={cycles} ***")

results.sort()
print(f"\n=== TOP 30 ===")
for entry in results[:30]:
    print(f"  {entry}")
print(f"\nBest overall: cycles={best_cycles}")
