#!/usr/bin/env python3
"""Verify the best configurations found - run each 3 times."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test

configs = [
    # (seed, cw, sw)
    (202, 388, 5120),
    (202, 390, 5120),
    (202, 420, 5120),
    (55, 400, 5000),
    (55, 400, 5120),
    (89, 260, 3000),
    (121, 260, 3000),
    (121, 320, 4000),
    # Also try the original best
    (202, 220, 5120),
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
    cycles_list = []
    for trial in range(3):
        cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
        cycles_list.append(cycles)
    print(f"seed={seed}, cw={cw:3d}, sw={sw:4d}: {cycles_list} (consistent={len(set(cycles_list))==1})")
