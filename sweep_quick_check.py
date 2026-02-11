#!/usr/bin/env python3
"""Quick check: try promising weight combos with all top seeds."""
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

# Try each seed with many different weight combos
all_seeds = list(range(0, 501))  # All seeds 0-500
# But first narrow down: for each seed, try a few weight combos
promising_weights = [
    (180, 4000), (200, 4500), (220, 5120), (240, 5500),
    (180, 5000), (200, 5120), (220, 4000), (240, 4500),
    (160, 3500), (260, 6000), (300, 7000), (150, 3000),
    (200, 6000), (220, 3000), (250, 5120), (280, 4000),
    (170, 4500), (190, 5000), (210, 5500), (230, 6000),
]

results = []
for seed in all_seeds:
    for cw, sw in promising_weights:
        kwargs = dict(baseline_kwargs)
        kwargs['scheduler_random_seed'] = seed
        kwargs['scheduler_crit_weight'] = cw
        kwargs['scheduler_succ_weight'] = sw
        try:
            cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
            if cycles <= 1382:
                results.append((cycles, seed, cw, sw))
            if cycles < best_cycles:
                best_cycles = cycles
                best_config = (seed, cw, sw)
                print(f"*** NEW BEST: seed={seed}, cw={cw}, sw={sw}, cycles={cycles} ***")
        except Exception as e:
            pass

results.sort()
print(f"\n=== ALL RESULTS <= 1382 ===")
for entry in results:
    print(f"  {entry}")
print(f"\nBest overall: cycles={best_cycles}, config={best_config}")
