"""Phase 4b: Test hash splitting and depth-2 optimizations."""
import sys
import random
from problem import Tree, Input, build_mem_image, VLEN, N_CORES, Machine
from perf_takehome import KernelBuilder, reference_kernel2

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
        for ref_mem in reference_kernel2(mem, {}):
            pass
        inp_values_p = ref_mem[6]
        if machine.mem[inp_values_p:inp_values_p + len(inp.values)] != ref_mem[inp_values_p:inp_values_p + len(inp.values)]:
            return None
        return machine.cycle
    except Exception as e:
        print(f"  ERROR: {e}")
        return None

if __name__ == "__main__":
    configs = [
        ({"split_hash_pairs": False}, "baseline (bundled)"),
        ({"split_hash_pairs": True}, "split hash pairs"),
        ({"split_hash_pairs": True, "scheduler_crit_weight": 512}, "split + crit=512"),
        ({"split_hash_pairs": True, "scheduler_crit_weight": 2048}, "split + crit=2048"),
        ({"split_hash_pairs": True, "scheduler_crit_weight": 4096}, "split + crit=4096"),
        ({"split_hash_pairs": True, "scheduler_crit_weight": 256}, "split + crit=256"),
        ({"split_hash_pairs": True, "scheduler_crit_weight": 128}, "split + crit=128"),
        ({"split_hash_pairs": True, "scheduler_engine_bias": {"load": 200}}, "split + load_bias=200"),
        ({"split_hash_pairs": True, "scheduler_engine_bias": {"valu": -100}}, "split + valu_bias=-100"),
        ({"split_hash_pairs": True, "scheduler_engine_bias": {"flow": 500}}, "split + flow_bias=500"),
        ({"split_hash_pairs": True, "scheduler_engine_bias": {"load": -200}}, "split + load_bias=-200"),
    ]

    best = 99999
    for kwargs, label in configs:
        cycles = measure_cycles(kwargs)
        status = f"CORRECT {cycles}" if cycles else "INCORRECT"
        marker = " ***" if cycles and cycles < best else ""
        if cycles and cycles < best:
            best = cycles
        print(f"  {label}: {status}{marker}")

    print(f"\nBest: {best}")
