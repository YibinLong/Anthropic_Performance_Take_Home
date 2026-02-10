"""Test combined optimizations."""
import random
from problem import Tree, Input, build_mem_image, VLEN, N_CORES, Machine
from perf_takehome import KernelBuilder, reference_kernel2

def measure(kwargs, seed=123):
    random.seed(seed)
    forest = Tree.generate(10)
    inp = Input.generate(forest, 256, 16)
    mem = build_mem_image(forest, inp)
    kb = KernelBuilder(**kwargs)
    kb.build_kernel(forest.height, len(forest.values), len(inp.indices), 16)
    machine = Machine(mem, kb.instrs, kb.debug_info(), n_cores=N_CORES, value_trace={}, trace=False)
    machine.prints = False
    machine.run()
    for ref_mem in reference_kernel2(mem, {}):
        pass
    inp_values_p = ref_mem[6]
    correct = machine.mem[inp_values_p:inp_values_p + len(inp.values)] == ref_mem[inp_values_p:inp_values_p + len(inp.values)]
    return machine.cycle, correct, kb.scratch_ptr

configs = [
    ({}, "baseline"),
    ({"split_hash_pairs": True, "scheduler_succ_weight": 512}, "split+succ512"),
    ({"split_hash_pairs": True, "scheduler_succ_weight": 512}, "split+succ512 (with precomp addrs)"),
]

for kwargs, label in configs:
    cycles, correct, scratch = measure(kwargs)
    print(f"  {label}: {cycles} cycles, correct={correct}, scratch={scratch}/1536")
