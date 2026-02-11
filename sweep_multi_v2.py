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

# Best seeds from sweep (1382 and 1383 level)
top_seeds = [202, 208, 269, 9, 55, 89, 121, 200, 229, 234, 282, 308, 479]

results = []
best_cycles = 1382
best_config = None

# Try pairs of top seeds
print("=== Pairs ===")
for combo in itertools.combinations(top_seeds, 2):
    kwargs = dict(baseline_kwargs)
    kwargs['scheduler_random_seed'] = combo[0]
    kwargs['scheduler_multi_start_seeds'] = list(combo[1:])
    try:
        cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
        results.append((cycles, list(combo)))
        if cycles < best_cycles:
            best_cycles = cycles
            best_config = combo
            print(f"*** NEW BEST: seeds={combo}, cycles={cycles} ***")
    except Exception as e:
        pass

# Try triples of top 1382 seeds
print("\n=== Triples ===")
top3 = [202, 208, 269]
for combo in itertools.combinations(top_seeds, 3):
    kwargs = dict(baseline_kwargs)
    kwargs['scheduler_random_seed'] = combo[0]
    kwargs['scheduler_multi_start_seeds'] = list(combo[1:])
    try:
        cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
        results.append((cycles, list(combo)))
        if cycles < best_cycles:
            best_cycles = cycles
            best_config = combo
            print(f"*** NEW BEST: seeds={combo}, cycles={cycles} ***")
    except Exception as e:
        pass

# Try 5-seed combos from the top
print("\n=== 5-seed combos ===")
for combo in itertools.combinations(top_seeds[:7], 5):
    kwargs = dict(baseline_kwargs)
    kwargs['scheduler_random_seed'] = combo[0]
    kwargs['scheduler_multi_start_seeds'] = list(combo[1:])
    try:
        cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
        results.append((cycles, list(combo)))
        if cycles < best_cycles:
            best_cycles = cycles
            best_config = combo
            print(f"*** NEW BEST: seeds={combo}, cycles={cycles} ***")
    except Exception as e:
        pass

# Try larger ranges
print("\n=== Large ranges ===")
for seed_list in [
    list(range(0, 20)),
    list(range(200, 220)),
    list(range(0, 50)),
    list(range(0, 100)),
    top_seeds,
    top_seeds[:5],
    top_seeds[:7],
    top_seeds[:10],
]:
    kwargs = dict(baseline_kwargs)
    kwargs['scheduler_random_seed'] = seed_list[0]
    kwargs['scheduler_multi_start_seeds'] = seed_list[1:]
    try:
        cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
        results.append((cycles, seed_list[:3]))
        if cycles < best_cycles:
            best_cycles = cycles
            best_config = seed_list
            print(f"*** NEW BEST: seeds={seed_list[:5]}..., cycles={cycles} ***")
        else:
            print(f"  seeds={seed_list[:3]}... (len={len(seed_list)}): {cycles} cycles")
    except Exception as e:
        print(f"  seeds failed: {e}")

results.sort(key=lambda x: x[0])
print(f"\n=== TOP 20 ===")
for cycles, seeds in results[:20]:
    print(f"  seeds={seeds}: {cycles} cycles")
print(f"\nBest: cycles={best_cycles}, config={best_config}")
