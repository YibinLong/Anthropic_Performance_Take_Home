#!/usr/bin/env python3
"""3D sweep: seed x crit_weight x succ_weight with actual defaults."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test

best_cycles = 1375
best_config = None

# Good seeds from sweep
good_seeds = [15, 61, 63, 154, 168, 202, 220, 244, 274, 275, 278, 284, 287, 291, 295, 330]

for seed in good_seeds:
    for cw in range(100, 500, 20):
        for sw in [1000, 1500, 2000, 2500, 3000, 4000, 5000, 6000]:
            kwargs = {
                'scheduler_random_seed': seed,
                'scheduler_crit_weight': cw,
                'scheduler_succ_weight': sw,
                'scheduler_beam_width': 1,
                'interleave_groups': 25,
                'interleave_groups_early': 29,
                'split_hash_pairs': True,
            }
            cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
            if cycles < best_cycles:
                best_cycles = cycles
                best_config = (seed, cw, sw)
                print(f"*** NEW BEST: seed={seed}, cw={cw}, sw={sw}, cycles={cycles} ***")

print(f"\nBest: {best_cycles}, config={best_config}")
