#!/usr/bin/env python3
"""Focused sweep: best 3 seeds x fine weight grid."""
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
best_config = None

# Best 3 seeds
seeds_to_try = [202, 208, 269]

# Fine weight grid around current best
crit_weights = list(range(150, 350, 2))
succ_weights = list(range(4000, 7000, 100))

for seed in seeds_to_try:
    for cw in crit_weights:
        for sw in succ_weights:
            kwargs = dict(baseline_kwargs)
            kwargs['scheduler_random_seed'] = seed
            kwargs['scheduler_crit_weight'] = cw
            kwargs['scheduler_succ_weight'] = sw
            try:
                cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
                results.append((cycles, seed, cw, sw))
                if cycles < best_cycles:
                    best_cycles = cycles
                    best_config = (seed, cw, sw)
                    print(f"*** NEW BEST: seed={seed}, cw={cw}, sw={sw}, cycles={cycles} ***")
            except Exception as e:
                pass

results.sort()
print(f"\n=== TOP 30 ===")
for entry in results[:30]:
    print(f"  {entry}")
print(f"\nBest overall: cycles={best_cycles}, config={best_config}")
