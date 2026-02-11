#!/usr/bin/env python3
"""Sweep crit_weight, succ_weight, beam_width, and other parameters."""
import sys
sys.path.insert(0, '/Users/work/Documents/WORKZONE/CODE/Anthropic_Performance_Take_Home_claude_code_try')
from perf_takehome import do_kernel_test

baseline_kwargs = {
    'scheduler_random_seed': 202,
    'interleave_groups': 25,
    'interleave_groups_early': 29,
    'split_hash_pairs': True,
}

results = []
best_cycles = 1382
best_config = None

# Phase 1: Sweep crit_weight and succ_weight together
print("=== Phase 1: crit_weight x succ_weight ===")
crit_weights = [50, 100, 150, 180, 200, 210, 220, 230, 240, 260, 300, 400]
succ_weights = [1000, 2000, 3000, 4000, 5000, 5120, 6000, 7000, 8000, 10000]

for cw in crit_weights:
    for sw in succ_weights:
        kwargs = dict(baseline_kwargs)
        kwargs['scheduler_crit_weight'] = cw
        kwargs['scheduler_succ_weight'] = sw
        kwargs['scheduler_beam_width'] = 1
        try:
            cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
            results.append((cycles, {'crit_weight': cw, 'succ_weight': sw, 'beam_width': 1}))
            if cycles < best_cycles:
                best_cycles = cycles
                best_config = {'crit_weight': cw, 'succ_weight': sw}
                print(f"*** NEW BEST: cw={cw}, sw={sw}, cycles={cycles} ***")
        except Exception as e:
            print(f"cw={cw}, sw={sw} failed: {e}")

# Phase 2: Sweep beam_width
print("\n=== Phase 2: beam_width ===")
for bw in [1, 2, 3, 4, 5, 6, 8]:
    kwargs = dict(baseline_kwargs)
    kwargs['scheduler_crit_weight'] = 220
    kwargs['scheduler_succ_weight'] = 5120
    kwargs['scheduler_beam_width'] = bw
    try:
        cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
        results.append((cycles, {'beam_width': bw}))
        if cycles < best_cycles:
            best_cycles = cycles
            print(f"*** NEW BEST: beam_width={bw}, cycles={cycles} ***")
    except Exception as e:
        print(f"bw={bw} failed: {e}")

# Phase 3: depth3_deterministic and depth4_mode
print("\n=== Phase 3: depth modes ===")
for d3 in [False, True]:
    for d4 in ["off", "deterministic16"]:
        kwargs = dict(baseline_kwargs)
        kwargs['scheduler_crit_weight'] = 220
        kwargs['scheduler_succ_weight'] = 5120
        kwargs['scheduler_beam_width'] = 1
        kwargs['depth3_deterministic'] = d3
        kwargs['depth4_mode'] = d4
        try:
            cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
            results.append((cycles, {'d3': d3, 'd4': d4}))
            if cycles < best_cycles:
                best_cycles = cycles
                print(f"*** NEW BEST: d3={d3}, d4={d4}, cycles={cycles} ***")
            else:
                print(f"  d3={d3}, d4={d4}: {cycles} cycles")
        except Exception as e:
            print(f"d3={d3}, d4={d4} failed: {e}")

# Phase 4: split_hash_pairs and scalar_hybrid_count
print("\n=== Phase 4: split_hash_pairs and scalar_hybrid_count ===")
for shp in [True, False]:
    for shc in [0, 8, 16]:
        kwargs = dict(baseline_kwargs)
        kwargs['scheduler_crit_weight'] = 220
        kwargs['scheduler_succ_weight'] = 5120
        kwargs['scheduler_beam_width'] = 1
        kwargs['split_hash_pairs'] = shp
        kwargs['scalar_hybrid_count'] = shc
        try:
            cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
            results.append((cycles, {'shp': shp, 'shc': shc}))
            if cycles < best_cycles:
                best_cycles = cycles
                print(f"*** NEW BEST: shp={shp}, shc={shc}, cycles={cycles} ***")
            else:
                print(f"  shp={shp}, shc={shc}: {cycles} cycles")
        except Exception as e:
            print(f"shp={shp}, shc={shc} failed: {e}")

# Phase 5: engine_bias
print("\n=== Phase 5: engine_bias ===")
biases = [
    {},
    {"load": 50},
    {"load": 100},
    {"load": 200},
    {"valu": 50},
    {"valu": 100},
    {"valu": 200},
    {"flow": 50},
    {"flow": 100},
    {"flow": 200},
    {"alu": 50},
    {"alu": 100},
    {"alu": 200},
    {"store": 50},
    {"store": 100},
    {"load": 100, "valu": 100},
    {"load": 200, "valu": 100},
    {"load": 100, "flow": 100},
    {"valu": 100, "flow": 100},
    {"load": -100},
    {"valu": -100},
    {"flow": -100},
    {"alu": -100},
]

for bias in biases:
    kwargs = dict(baseline_kwargs)
    kwargs['scheduler_crit_weight'] = 220
    kwargs['scheduler_succ_weight'] = 5120
    kwargs['scheduler_beam_width'] = 1
    kwargs['scheduler_engine_bias'] = bias
    try:
        cycles = do_kernel_test(10, 16, 256, kernel_kwargs=kwargs)
        results.append((cycles, {'bias': bias}))
        if cycles < best_cycles:
            best_cycles = cycles
            print(f"*** NEW BEST: bias={bias}, cycles={cycles} ***")
        else:
            print(f"  bias={bias}: {cycles} cycles")
    except Exception as e:
        print(f"bias={bias} failed: {e}")

results.sort()
print("\n\n=== TOP 30 OVERALL ===")
for cycles, config in results[:30]:
    print(f"  {config}: {cycles} cycles")
print(f"\nBest: cycles={best_cycles}")
