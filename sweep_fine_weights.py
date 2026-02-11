#!/usr/bin/env python3
"""Fine-grained weight sweep around current best values."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test

baseline_kwargs = {
    'scheduler_random_seed': 202,
    'scheduler_beam_width': 1,
    'interleave_groups': 25,
    'interleave_groups_early': 29,
    'split_hash_pairs': True,
}

results = []
best_cycles = 1382

# Very fine crit_weight sweep
print("=== Fine crit_weight sweep (seed=202) ===")
for cw in range(100, 501, 5):
    for sw in [3000, 4000, 5000, 5120, 6000, 7000, 8000]:
        kwargs = dict(baseline_kwargs)
        kwargs['scheduler_crit_weight'] = cw
        kwargs['scheduler_succ_weight'] = sw
        cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
        results.append((cycles, cw, sw))
        if cycles < best_cycles:
            best_cycles = cycles
            print(f"*** NEW BEST: cw={cw}, sw={sw}, cycles={cycles} ***")

# Try with seed 208 and 269
for seed in [208, 269]:
    print(f"\n=== Fine crit_weight sweep (seed={seed}) ===")
    for cw in range(100, 501, 5):
        for sw in [3000, 4000, 5000, 5120, 6000, 7000, 8000]:
            kwargs = dict(baseline_kwargs)
            kwargs['scheduler_random_seed'] = seed
            kwargs['scheduler_crit_weight'] = cw
            kwargs['scheduler_succ_weight'] = sw
            cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
            results.append((cycles, cw, sw, seed))
            if cycles < best_cycles:
                best_cycles = cycles
                print(f"*** NEW BEST: seed={seed}, cw={cw}, sw={sw}, cycles={cycles} ***")

results.sort()
print(f"\n=== TOP 20 ===")
for entry in results[:20]:
    print(f"  {entry}")
print(f"\nBest: cycles={best_cycles}")
