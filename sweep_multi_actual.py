#!/usr/bin/env python3
"""Multi-start seed sweep with actual defaults."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test
import itertools

best_cycles = 1375

# Good seeds from sweep
good_seeds = [15, 61, 63, 154, 168, 202, 220, 244, 274, 275, 278, 284, 287, 291, 295, 330, 349, 357, 410, 433, 459, 468]

# Try large multi-start combos
print("=== Large multi-start lists ===")
for size in [5, 10, 15, 22]:
    for start in range(0, len(good_seeds) - size + 1, max(1, size // 2)):
        subset = good_seeds[start:start+size]
        kwargs = {
            'scheduler_random_seed': subset[0],
            'scheduler_multi_start_seeds': subset[1:],
            'scheduler_crit_weight': 200,
            'scheduler_succ_weight': 2500,
            'scheduler_beam_width': 1,
            'interleave_groups': 25,
            'interleave_groups_early': 29,
            'split_hash_pairs': True,
        }
        cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
        if cycles < best_cycles:
            best_cycles = cycles
            print(f"*** NEW BEST: seeds={subset[:5]}... (len={len(subset)}), cycles={cycles} ***")

# Try dense ranges
print("\n=== Dense ranges as multi-start ===")
for start in [0, 50, 100, 150, 200, 250, 300]:
    for width in [20, 50, 100, 200]:
        seed_list = list(range(start, start + width))
        kwargs = {
            'scheduler_random_seed': seed_list[0],
            'scheduler_multi_start_seeds': seed_list[1:],
            'scheduler_crit_weight': 200,
            'scheduler_succ_weight': 2500,
            'scheduler_beam_width': 1,
            'interleave_groups': 25,
            'interleave_groups_early': 29,
            'split_hash_pairs': True,
        }
        cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
        if cycles < best_cycles:
            best_cycles = cycles
            print(f"*** NEW BEST: range({start},{start+width}), cycles={cycles} ***")
        else:
            print(f"  range({start},{start+width}): {cycles}")

# Try all 1375 seeds together
kwargs = {
    'scheduler_random_seed': good_seeds[0],
    'scheduler_multi_start_seeds': good_seeds[1:],
    'scheduler_crit_weight': 200,
    'scheduler_succ_weight': 2500,
    'scheduler_beam_width': 1,
    'interleave_groups': 25,
    'interleave_groups_early': 29,
    'split_hash_pairs': True,
}
cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
print(f"\nAll good seeds together: {cycles}")

# Try None seed (no randomization)
kwargs2 = {
    'scheduler_random_seed': None,
    'scheduler_crit_weight': 200,
    'scheduler_succ_weight': 2500,
    'scheduler_beam_width': 1,
    'interleave_groups': 25,
    'interleave_groups_early': 29,
    'split_hash_pairs': True,
}
cycles2 = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs2)
print(f"No randomization (seed=None): {cycles2}")

print(f"\nBest: {best_cycles}")
