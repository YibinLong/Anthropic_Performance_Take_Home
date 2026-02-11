#!/usr/bin/env python3
"""Quick sweep of beam_width."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test

baseline_kwargs = {
    'scheduler_random_seed': 202,
    'scheduler_crit_weight': 220,
    'scheduler_succ_weight': 5120,
    'interleave_groups': 25,
    'interleave_groups_early': 29,
    'split_hash_pairs': True,
}

for bw in [1, 2, 3, 4, 5, 6, 8, 10, 12, 16]:
    kwargs = dict(baseline_kwargs)
    kwargs['scheduler_beam_width'] = bw
    cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
    print(f"beam_width={bw}: {cycles} cycles")
