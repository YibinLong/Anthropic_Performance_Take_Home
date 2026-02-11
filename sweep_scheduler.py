"""Sweep scheduler priority schemes and random restarts."""
import random
from problem import Tree, Input, build_mem_image, VLEN, N_CORES, Machine
from perf_takehome import KernelBuilder, reference_kernel2

def measure_cycles(kwargs, seed=123):
    random.seed(seed)
    forest = Tree.generate(10)
    inp = Input.generate(forest, 256, 16)
    mem = build_mem_image(forest, inp)
    try:
        kb = KernelBuilder(**kwargs)
        kb.build_kernel(forest.height, len(forest.values), len(inp.indices), 16)
        machine = Machine(mem, kb.instrs, kb.debug_info(), n_cores=N_CORES, value_trace={}, trace=False)
        machine.prints = False
        machine.run()
        for ref_mem in reference_kernel2(mem, {}):
            pass
        inp_values_p = ref_mem[6]
        if machine.mem[inp_values_p:inp_values_p + len(inp.values)] != ref_mem[inp_values_p:inp_values_p + len(inp.values)]:
            return None
        return machine.cycle
    except Exception as e:
        return None

if __name__ == "__main__":
    best = 99999
    best_cfg = ""

    # Test successor weight
    print("=== Successor Weight ===")
    for sw in [0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512]:
        c = measure_cycles({"scheduler_succ_weight": sw, "split_hash_pairs": True})
        marker = " ***" if c and c < best else ""
        if c and c < best:
            best = c
            best_cfg = f"succ_weight={sw}"
        print(f"  succ_weight={sw}: {c}{marker}")

    # Test random restarts (50 seeds)
    print("\n=== Random Restarts (split_hash_pairs=True) ===")
    for seed in range(50):
        c = measure_cycles({"scheduler_random_seed": seed, "split_hash_pairs": True})
        marker = " ***" if c and c < best else ""
        if c and c < best:
            best = c
            best_cfg = f"random_seed={seed}"
        if c and (c < 1443 or marker):
            print(f"  seed={seed}: {c}{marker}")

    # Test random restarts with successor weight
    print("\n=== Random Restarts + succ_weight=64 ===")
    for seed in range(50):
        c = measure_cycles({"scheduler_random_seed": seed, "scheduler_succ_weight": 64, "split_hash_pairs": True})
        marker = " ***" if c and c < best else ""
        if c and c < best:
            best = c
            best_cfg = f"random_seed={seed}_succ=64"
        if c and (c < 1443 or marker):
            print(f"  seed={seed}: {c}{marker}")

    print(f"\nBest: {best} ({best_cfg})")
