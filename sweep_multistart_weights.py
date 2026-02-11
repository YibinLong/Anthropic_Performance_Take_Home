#!/usr/bin/env python3
"""Try multi-start seeds with different weights."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test

baseline_kwargs = {
    'scheduler_beam_width': 1,
    'interleave_groups': 25,
    'interleave_groups_early': 29,
    'split_hash_pairs': True,
}

best_cycles = 1382
best_config = None
results = []

# The key insight: multi_start_seeds tries each seed and picks the one
# with fewest cycles. So we want seeds that are good at DIFFERENT weight combos.
multi_seed_lists = [
    [202, 208, 269],
    [202, 208, 269, 9, 55, 89],
    [202, 208, 269, 9, 55, 89, 121, 200, 229, 234],
    list(range(0, 50)),
    list(range(0, 100)),
    list(range(200, 300)),
]

crit_weights = list(range(100, 400, 10))
succ_weights = [3000, 4000, 5000, 5120, 6000, 7000]

for multi_seeds in multi_seed_lists:
    print(f"\n=== Multi-start seeds: {multi_seeds[:5]}... (len={len(multi_seeds)}) ===")
    for cw in crit_weights:
        for sw in succ_weights:
            kwargs = dict(baseline_kwargs)
            kwargs['scheduler_random_seed'] = multi_seeds[0]
            kwargs['scheduler_multi_start_seeds'] = multi_seeds[1:]
            kwargs['scheduler_crit_weight'] = cw
            kwargs['scheduler_succ_weight'] = sw
            try:
                cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
                if cycles <= 1382:
                    results.append((cycles, multi_seeds[:3], cw, sw))
                if cycles < best_cycles:
                    best_cycles = cycles
                    best_config = (multi_seeds[:5], cw, sw)
                    print(f"*** NEW BEST: seeds={multi_seeds[:5]}..., cw={cw}, sw={sw}, cycles={cycles} ***")
            except Exception as e:
                pass

results.sort(key=lambda x: x[0])
print(f"\n=== ALL RESULTS <= 1382 ===")
for entry in results:
    print(f"  {entry}")
print(f"\nBest overall: cycles={best_cycles}, config={best_config}")
