#!/usr/bin/env python3
"""Sweep multi-start seeds using the best seeds found."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test
import itertools

baseline_kwargs = {
    'scheduler_crit_weight': 220,
    'scheduler_succ_weight': 5120,
    'scheduler_beam_width': 1,
    'interleave_groups': 25,
    'interleave_groups_early': 29,
    'split_hash_pairs': True,
}

# Best seeds from sweep
top_seeds = [202, 208, 269, 9, 55, 89, 121, 200, 229, 234, 282, 308, 479]

results = []
best_cycles = 1382

# Try all combinations of 2-5 top seeds
for size in range(2, 8):
    for combo in itertools.combinations(top_seeds, size):
        kwargs = dict(baseline_kwargs)
        kwargs['scheduler_random_seed'] = combo[0]
        kwargs['scheduler_multi_start_seeds'] = list(combo[1:])
        try:
            cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
            results.append((cycles, combo))
            if cycles < best_cycles:
                best_cycles = cycles
                print(f"*** NEW BEST: seeds={combo}, cycles={cycles} ***")
        except Exception as e:
            print(f"seeds={combo} failed: {e}")
        # Early exit optimization - skip remaining combos of this size
        # if we already found something good

results.sort()
print("\n\n=== TOP 20 MULTI-SEED COMBOS ===")
for cycles, seeds in results[:20]:
    print(f"  seeds={seeds}: {cycles} cycles")
print(f"\nBest: cycles={best_cycles}")
