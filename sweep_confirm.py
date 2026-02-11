#!/usr/bin/env python3
"""Confirm the best results from first fine weight sweep."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test

# Configurations that allegedly beat 1382 in the first sweep
configs = [
    (202, 100, 3000),  # 1380
    (202, 110, 3000),  # 1379
    (202, 150, 3000),  # 1378
    (202, 225, 3000),  # 1377
    (202, 335, 4000),  # 1376
    (202, 390, 5000),  # 1375
]

for seed, cw, sw in configs:
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
    print(f"seed={seed}, cw={cw}, sw={sw}: {cycles} cycles")
