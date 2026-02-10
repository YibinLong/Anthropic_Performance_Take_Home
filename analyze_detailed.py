"""Detailed schedule analysis: where are the idle VALU slots?"""
import random
from problem import Tree, Input, build_mem_image, VLEN, N_CORES, Machine, SLOT_LIMITS
from perf_takehome import KernelBuilder

random.seed(123)
forest = Tree.generate(10)
inp = Input.generate(forest, 256, 16)
mem = build_mem_image(forest, inp)

kb = KernelBuilder()
kb.build_kernel(forest.height, len(forest.values), len(inp.indices), 16)

# Distribution of VALU slots per cycle
from collections import Counter
valu_dist = Counter()
load_dist = Counter()
flow_dist = Counter()
for instr in kb.instrs:
    has_non_debug = any(e != "debug" for e in instr)
    if not has_non_debug:
        continue
    valu_dist[len(instr.get("valu", []))] += 1
    load_dist[len(instr.get("load", []))] += 1
    flow_dist[len(instr.get("flow", []))] += 1

print("VALU slots/cycle distribution:")
for k in sorted(valu_dist.keys()):
    print(f"  {k} slots: {valu_dist[k]} cycles ({valu_dist[k]/sum(valu_dist.values())*100:.1f}%)")

print("\nLoad slots/cycle distribution:")
for k in sorted(load_dist.keys()):
    print(f"  {k} slots: {load_dist[k]} cycles ({load_dist[k]/sum(load_dist.values())*100:.1f}%)")

print("\nFlow slots/cycle distribution:")
for k in sorted(flow_dist.keys()):
    print(f"  {k} slots: {flow_dist[k]} cycles ({flow_dist[k]/sum(flow_dist.values())*100:.1f}%)")

# Where are the low-VALU cycles?
# Check beginning and end
total_cycles = sum(valu_dist.values())
print(f"\nTotal cycles: {total_cycles}")

# First/last 50 cycles
first_50_valu = sum(len(kb.instrs[i].get("valu", [])) for i in range(min(50, len(kb.instrs))))
last_50_valu = sum(len(kb.instrs[i].get("valu", [])) for i in range(max(0, len(kb.instrs)-50), len(kb.instrs)))
print(f"First 50 cycles avg VALU: {first_50_valu/50:.2f}")
print(f"Last 50 cycles avg VALU: {last_50_valu/50:.2f}")

# Count consecutive low-VALU runs (< 4 slots)
low_runs = []
current_run = 0
for instr in kb.instrs:
    has_non_debug = any(e != "debug" for e in instr)
    if not has_non_debug:
        continue
    valu = len(instr.get("valu", []))
    if valu < 4:
        current_run += 1
    else:
        if current_run > 0:
            low_runs.append(current_run)
        current_run = 0
if current_run > 0:
    low_runs.append(current_run)

print(f"\nLow-VALU runs (< 4 slots): {len(low_runs)} runs")
if low_runs:
    print(f"  Max run: {max(low_runs)}")
    print(f"  Total cycles in low runs: {sum(low_runs)}")
    print(f"  Run length distribution: {Counter(low_runs).most_common(10)}")

# Co-occurrence: cycles with low VALU AND high load
low_valu_high_load = 0
low_valu_with_flow = 0
zero_valu = 0
for instr in kb.instrs:
    has_non_debug = any(e != "debug" for e in instr)
    if not has_non_debug:
        continue
    v = len(instr.get("valu", []))
    l = len(instr.get("load", []))
    f = len(instr.get("flow", []))
    if v < 4 and l == 2:
        low_valu_high_load += 1
    if v < 4 and f > 0:
        low_valu_with_flow += 1
    if v == 0:
        zero_valu += 1

print(f"\nCo-occurrence:")
print(f"  Low VALU (<4) AND load saturated (2): {low_valu_high_load}")
print(f"  Low VALU (<4) AND flow active: {low_valu_with_flow}")
print(f"  Zero VALU: {zero_valu}")
