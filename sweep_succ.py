"""Deep sweep of successor weight."""
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

    # Sweep succ_weight more finely around the good range
    print("=== Fine succ_weight sweep (split=True) ===")
    for sw in [256, 384, 512, 640, 768, 1024, 1536, 2048, 3072, 4096, 8192, 16384]:
        c = measure_cycles({"scheduler_succ_weight": sw, "split_hash_pairs": True})
        marker = " ***" if c and c < best else ""
        if c and c < best:
            best = c
            best_cfg = f"split+succ={sw}"
        print(f"  succ_weight={sw}: {c}{marker}")

    # Same without split
    print("\n=== Fine succ_weight sweep (split=False) ===")
    for sw in [256, 512, 1024, 2048, 4096, 8192]:
        c = measure_cycles({"scheduler_succ_weight": sw, "split_hash_pairs": False})
        marker = " ***" if c and c < best else ""
        if c and c < best:
            best = c
            best_cfg = f"nosplit+succ={sw}"
        print(f"  succ_weight={sw}: {c}{marker}")

    # Try combining succ_weight with crit_weight variations
    print("\n=== succ_weight + crit_weight combos ===")
    for cw in [256, 512, 1024, 2048]:
        for sw in [512, 1024, 2048, 4096]:
            c = measure_cycles({"scheduler_crit_weight": cw, "scheduler_succ_weight": sw, "split_hash_pairs": True})
            marker = " ***" if c and c < best else ""
            if c and c < best:
                best = c
                best_cfg = f"crit={cw}_succ={sw}_split"
            print(f"  crit={cw} succ={sw}: {c}{marker}")

    # Try adding random restarts to the best configs
    print("\n=== Best + random restarts ===")
    for seed in range(30):
        c = measure_cycles({"scheduler_succ_weight": best_sw if 'best_sw' in dir() else 512, "split_hash_pairs": True, "scheduler_random_seed": seed, "scheduler_crit_weight": 1024})
        marker = " ***" if c and c < best else ""
        if c and c < best:
            best = c
            best_cfg = f"succ=512_seed={seed}"
        if c and c < 1430:
            print(f"  seed={seed}: {c}{marker}")

    print(f"\nBest: {best} ({best_cfg})")
