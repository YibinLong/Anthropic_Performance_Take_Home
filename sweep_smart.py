#!/usr/bin/env python3
"""Smart sweep: coarse grid first, then fine-tune around best."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test

baseline_kwargs = {
    'scheduler_beam_width': 1,
    'interleave_groups': 25,
    'interleave_groups_early': 29,
    'split_hash_pairs': True,
}

results = []
best_cycles = 1382
best_config = None

# Best 3 seeds at 1382
seeds = [202, 208, 269]
# Also check 1383-level seeds with different weights
seeds_1383 = [9, 55, 89, 121, 200, 229, 234, 282, 308, 479]

# Phase 1: Coarse grid for all seeds
print("=== Phase 1: Coarse grid for 1382-tier seeds ===")
crit_coarse = list(range(100, 500, 20))
succ_coarse = [2000, 3000, 4000, 5000, 5120, 6000, 7000, 8000, 10000]

for seed in seeds:
    for cw in crit_coarse:
        for sw in succ_coarse:
            kwargs = dict(baseline_kwargs)
            kwargs['scheduler_random_seed'] = seed
            kwargs['scheduler_crit_weight'] = cw
            kwargs['scheduler_succ_weight'] = sw
            try:
                cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
                results.append((cycles, seed, cw, sw))
                if cycles < best_cycles:
                    best_cycles = cycles
                    best_config = (seed, cw, sw)
                    print(f"*** NEW BEST: seed={seed}, cw={cw}, sw={sw}, cycles={cycles} ***")
            except Exception as e:
                pass

print(f"\nPhase 1 best: {best_cycles}, config={best_config}")

# Phase 2: Same for 1383-tier seeds
print("\n=== Phase 2: Coarse grid for 1383-tier seeds ===")
for seed in seeds_1383:
    for cw in crit_coarse:
        for sw in succ_coarse:
            kwargs = dict(baseline_kwargs)
            kwargs['scheduler_random_seed'] = seed
            kwargs['scheduler_crit_weight'] = cw
            kwargs['scheduler_succ_weight'] = sw
            try:
                cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
                results.append((cycles, seed, cw, sw))
                if cycles < best_cycles:
                    best_cycles = cycles
                    best_config = (seed, cw, sw)
                    print(f"*** NEW BEST: seed={seed}, cw={cw}, sw={sw}, cycles={cycles} ***")
            except Exception as e:
                pass

print(f"\nPhase 2 best: {best_cycles}, config={best_config}")

# Phase 3: Fine grid around any improvements found
if best_config:
    best_seed, best_cw, best_sw = best_config
    print(f"\n=== Phase 3: Fine grid around seed={best_seed}, cw={best_cw}, sw={best_sw} ===")
    for cw in range(max(50, best_cw - 40), best_cw + 41, 2):
        for sw in range(max(500, best_sw - 500), best_sw + 501, 50):
            kwargs = dict(baseline_kwargs)
            kwargs['scheduler_random_seed'] = best_seed
            kwargs['scheduler_crit_weight'] = cw
            kwargs['scheduler_succ_weight'] = sw
            try:
                cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
                results.append((cycles, best_seed, cw, sw))
                if cycles < best_cycles:
                    best_cycles = cycles
                    best_config = (best_seed, cw, sw)
                    print(f"*** NEW BEST: seed={best_seed}, cw={cw}, sw={sw}, cycles={cycles} ***")
            except Exception as e:
                pass

results.sort()
print(f"\n=== TOP 30 ===")
for entry in results[:30]:
    print(f"  {entry}")
print(f"\nBest overall: cycles={best_cycles}, config={best_config}")
