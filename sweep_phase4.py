"""Phase 4: Parameter sweep for cycle reduction."""
import sys
import itertools
import random
from problem import Tree, Input, build_mem_image, VLEN, N_CORES, Machine
from perf_takehome import KernelBuilder

def measure_cycles(kwargs, seed=123, forest_height=10, rounds=16, batch_size=256):
    """Build kernel with given kwargs and return cycle count, or None on error."""
    random.seed(seed)
    forest = Tree.generate(forest_height)
    inp = Input.generate(forest, batch_size, rounds)
    mem = build_mem_image(forest, inp)
    try:
        kb = KernelBuilder(**kwargs)
        kb.build_kernel(forest.height, len(forest.values), len(inp.indices), rounds)
        machine = Machine(mem, kb.instrs, kb.debug_info(), n_cores=N_CORES, value_trace={}, trace=False)
        machine.prints = False
        machine.run()
        # Quick correctness check
        from perf_takehome import reference_kernel2
        for ref_mem in reference_kernel2(mem, {}):
            pass
        inp_values_p = ref_mem[6]
        if machine.mem[inp_values_p:inp_values_p + len(inp.values)] != ref_mem[inp_values_p:inp_values_p + len(inp.values)]:
            return None  # incorrect
        return machine.cycle
    except Exception as e:
        return None

if __name__ == "__main__":
    best_cycles = 99999
    best_config = None
    results = []

    # Sweep parameters
    configs = []

    # 1. Sweep crit_weight with current defaults
    for crit_w in [128, 256, 512, 768, 1024, 1536, 2048, 4096, 8192]:
        configs.append({"scheduler_crit_weight": crit_w, "label": f"crit={crit_w}"})

    # 2. Sweep idx_branch_mode
    for mode in ["flow_vselect", "alu_branch"]:
        configs.append({"idx_branch_mode": mode, "label": f"branch={mode}"})

    # 3. Sweep interleave_groups (late depths) - lower might help
    for g in [20, 22, 24, 25]:
        configs.append({"interleave_groups": g, "label": f"late_groups={g}"})

    # 4. Sweep interleave_groups_early
    for g in [25, 27, 29]:
        configs.append({"interleave_groups_early": g, "label": f"early_groups={g}"})

    # 5. Engine biases
    for bias_engine, bias_val in [("load", 100), ("load", 500), ("valu", 100), ("valu", 500), ("flow", 100), ("flow", 500)]:
        configs.append({
            "scheduler_engine_bias": {bias_engine: bias_val},
            "label": f"bias_{bias_engine}={bias_val}"
        })

    # 6. Combinations of best-looking single params
    for crit_w in [256, 512, 1024, 2048]:
        for mode in ["flow_vselect", "alu_branch"]:
            configs.append({
                "scheduler_crit_weight": crit_w,
                "idx_branch_mode": mode,
                "label": f"crit={crit_w}_branch={mode}"
            })

    # 7. Combined sweep with engine bias + crit_weight
    for crit_w in [512, 1024, 2048]:
        for bias_engine, bias_val in [("load", 200), ("valu", 200)]:
            configs.append({
                "scheduler_crit_weight": crit_w,
                "scheduler_engine_bias": {bias_engine: bias_val},
                "label": f"crit={crit_w}_bias_{bias_engine}={bias_val}"
            })

    print(f"Running {len(configs)} configurations...")
    for i, cfg in enumerate(configs):
        label = cfg.pop("label")
        cycles = measure_cycles(cfg)
        cfg["label"] = label
        status = f"CORRECT {cycles}" if cycles else "INCORRECT"
        marker = " ***" if cycles and cycles < best_cycles else ""
        print(f"[{i+1}/{len(configs)}] {label}: {status}{marker}")
        if cycles:
            results.append((cycles, label, cfg))
            if cycles < best_cycles:
                best_cycles = cycles
                best_config = cfg

    print(f"\n{'='*60}")
    print(f"Best: {best_cycles} cycles")
    print(f"Config: {best_config}")
    print(f"\nTop 10:")
    for cycles, label, cfg in sorted(results)[:10]:
        print(f"  {cycles}: {label}")
