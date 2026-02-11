"""Analyze exact operation counts and utilization."""
import random
from problem import Tree, Input, build_mem_image, VLEN, N_CORES, Machine, SLOT_LIMITS
from perf_takehome import KernelBuilder, analyze_utilization, format_utilization

random.seed(123)
forest = Tree.generate(10)
inp = Input.generate(forest, 256, 16)
mem = build_mem_image(forest, inp)

kb = KernelBuilder()
kb.build_kernel(forest.height, len(forest.values), len(inp.indices), 16)

print(f"scratch_ptr: {kb.scratch_ptr} / 1536")
print()

stats = analyze_utilization(kb.instrs)
print(format_utilization(stats))
print()

# Count ops by engine
engine_totals = {}
for instr in kb.instrs:
    for engine, slots in instr.items():
        if engine == "debug":
            continue
        engine_totals[engine] = engine_totals.get(engine, 0) + len(slots)

print("Op counts:")
for engine in sorted(engine_totals):
    limit = SLOT_LIMITS.get(engine, "?")
    min_cycles = engine_totals[engine] / limit if isinstance(limit, int) else "?"
    print(f"  {engine}: {engine_totals[engine]} ops / {limit} slots = {min_cycles:.1f} min cycles")

print(f"\nCycle count: {stats['cycle_count']}")
print(f"VALU min: {engine_totals.get('valu', 0) / 6:.1f}")
print(f"Load min: {engine_totals.get('load', 0) / 2:.1f}")
print(f"Flow min: {engine_totals.get('flow', 0)}")
print(f"Overhead: {stats['cycle_count'] - max(engine_totals.get('valu', 0) / 6, engine_totals.get('load', 0) / 2, engine_totals.get('flow', 0)):.1f}")

# Check how many cycles are load-saturated vs valu-saturated
load_sat = sum(1 for instr in kb.instrs if len(instr.get("load", [])) == 2 and any(e != "debug" for e in instr))
valu_sat = sum(1 for instr in kb.instrs if len(instr.get("valu", [])) == 6 and any(e != "debug" for e in instr))
flow_active = sum(1 for instr in kb.instrs if len(instr.get("flow", [])) > 0 and any(e != "debug" for e in instr))
print(f"\nSaturation analysis:")
print(f"  Load-saturated cycles (2/2): {load_sat}")
print(f"  VALU-saturated cycles (6/6): {valu_sat}")
print(f"  Flow-active cycles: {flow_active}")

# Check idle slots
total_load_idle = sum(2 - len(instr.get("load", [])) for instr in kb.instrs if any(e != "debug" for e in instr))
total_valu_idle = sum(6 - len(instr.get("valu", [])) for instr in kb.instrs if any(e != "debug" for e in instr))
print(f"  Load idle slots: {total_load_idle}")
print(f"  VALU idle slots: {total_valu_idle}")
