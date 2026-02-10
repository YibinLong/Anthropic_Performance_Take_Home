"""Test if relaxed WAR tracking (last-reader only) helps at 25 groups."""
import random
from copy import deepcopy
from collections import defaultdict
import heapq
from problem import Tree, Input, build_mem_image, VLEN, N_CORES, Machine, SLOT_LIMITS, SCRATCH_SIZE
from perf_takehome import KernelBuilder, reference_kernel2

def schedule_relaxed_war(kb, slots):
    """Schedule with last-reader-only WAR tracking (pre-fix behavior)."""
    if not slots:
        return []

    ops = []
    for engine, slot in slots:
        if isinstance(slot, list):
            reads, writes = set(), set()
            for subslot in slot:
                sr, sw = kb._slot_reads_writes(engine, subslot)
                reads.update(sr)
                writes.update(sw)
            ops.append((engine, slot, reads, writes, len(slot)))
        else:
            reads, writes = kb._slot_reads_writes(engine, slot)
            ops.append((engine, [slot], reads, writes, 1))

    n_ops = len(ops)
    strict_succs = [set() for _ in range(n_ops)]
    weak_succs = [set() for _ in range(n_ops)]
    strict_pred_count = [0] * n_ops
    weak_pred_count = [0] * n_ops

    last_write = [-1] * SCRATCH_SIZE
    last_read = [-1] * SCRATCH_SIZE  # single last reader (relaxed)

    for i, (_, _, reads, writes, _) in enumerate(ops):
        for addr in reads:
            lw = last_write[addr]
            if lw != -1 and i not in strict_succs[lw]:
                strict_succs[lw].add(i)
                strict_pred_count[i] += 1
            last_read[addr] = i
        for addr in writes:
            lw = last_write[addr]
            if lw != -1 and i not in strict_succs[lw]:
                strict_succs[lw].add(i)
                strict_pred_count[i] += 1
            lr = last_read[addr]
            if lr != -1 and lr != i and i not in weak_succs[lr]:
                weak_succs[lr].add(i)
                weak_pred_count[i] += 1
            last_write[addr] = i

    crit_path = [1] * n_ops
    for i in range(n_ops - 1, -1, -1):
        max_succ = 0
        for s in strict_succs[i]:
            if crit_path[s] > max_succ:
                max_succ = crit_path[s]
        for s in weak_succs[i]:
            if crit_path[s] > max_succ:
                max_succ = crit_path[s]
        crit_path[i] = 1 + max_succ

    op_priority = [0] * n_ops
    for i, (engine, _, _, _, _) in enumerate(ops):
        succ_count = len(strict_succs[i]) + len(weak_succs[i])
        op_priority[i] = crit_path[i] * 1024 + succ_count * 512

    ready_heap = []
    for i in range(n_ops):
        if strict_pred_count[i] == 0 and weak_pred_count[i] == 0:
            heapq.heappush(ready_heap, (-op_priority[i], i))

    max_strict_pred_cycle = [-1] * n_ops
    max_weak_pred_cycle = [-1] * n_ops
    scheduled = [False] * n_ops
    instrs = []
    cycle = 0
    remaining = n_ops

    while remaining > 0:
        bundle = {}
        engine_counts = defaultdict(int)
        deferred = []
        scheduled_any = False

        while ready_heap:
            neg_prio, i = heapq.heappop(ready_heap)
            if scheduled[i]:
                continue
            if max_strict_pred_cycle[i] + 1 > cycle:
                deferred.append((-op_priority[i], i))
                continue
            if max_weak_pred_cycle[i] > cycle:
                deferred.append((-op_priority[i], i))
                continue
            engine, slot_list, _, _, slot_count = ops[i]
            if engine_counts[engine] + slot_count > SLOT_LIMITS[engine]:
                deferred.append((-op_priority[i], i))
                continue

            scheduled_any = True
            scheduled[i] = True
            remaining -= 1
            engine_counts[engine] += slot_count
            bundle.setdefault(engine, []).extend(slot_list)

            for succ in strict_succs[i]:
                strict_pred_count[succ] -= 1
                if max_strict_pred_cycle[succ] < cycle:
                    max_strict_pred_cycle[succ] = cycle
                if strict_pred_count[succ] == 0 and weak_pred_count[succ] == 0:
                    heapq.heappush(ready_heap, (-op_priority[succ], succ))
            for succ in weak_succs[i]:
                weak_pred_count[succ] -= 1
                if max_weak_pred_cycle[succ] < cycle:
                    max_weak_pred_cycle[succ] = cycle
                if strict_pred_count[succ] == 0 and weak_pred_count[succ] == 0:
                    heapq.heappush(ready_heap, (-op_priority[succ], succ))

        if not scheduled_any:
            raise RuntimeError("Scheduler deadlock")

        instrs.append(bundle)
        cycle += 1
        if deferred:
            heapq.heapify(deferred)
            ready_heap = deferred
        else:
            ready_heap = []

    return instrs


def test_relaxed():
    """Build kernel and test with relaxed WAR scheduler."""
    random.seed(123)
    forest = Tree.generate(10)
    inp = Input.generate(forest, 256, 16)
    mem = build_mem_image(forest, inp)

    kb = KernelBuilder(split_hash_pairs=True, scheduler_succ_weight=512)
    kb.build_kernel(forest.height, len(forest.values), len(inp.indices), 16)
    print(f"Normal schedule: {len(kb.instrs)} cycles")

    # Now rebuild with relaxed WAR by intercepting the build
    random.seed(123)
    kb2 = KernelBuilder(split_hash_pairs=True)

    # Monkey-patch the _schedule_vliw to use relaxed WAR
    original_schedule = kb2._schedule_vliw
    def patched_schedule(slots, phase_tag=None):
        return schedule_relaxed_war(kb2, slots)
    kb2._schedule_vliw = patched_schedule

    kb2.build_kernel(forest.height, len(forest.values), len(inp.indices), 16)
    print(f"Relaxed WAR schedule: {len(kb2.instrs)} cycles")

    # Check correctness
    machine = Machine(mem, kb2.instrs, kb2.debug_info(), n_cores=N_CORES, value_trace={}, trace=False)
    machine.prints = False
    machine.run()
    for ref_mem in reference_kernel2(mem, {}):
        pass
    inp_values_p = ref_mem[6]
    correct = machine.mem[inp_values_p:inp_values_p + len(inp.values)] == ref_mem[inp_values_p:inp_values_p + len(inp.values)]
    print(f"Correctness: {correct}")

    # Test across 8 random seeds (like submission tests)
    if correct:
        all_correct = True
        for _ in range(8):
            forest2 = Tree.generate(10)
            inp2 = Input.generate(forest2, 256, 16)
            mem2 = build_mem_image(forest2, inp2)
            machine2 = Machine(mem2, kb2.instrs, kb2.debug_info(), n_cores=N_CORES, value_trace={}, trace=False)
            machine2.prints = False
            machine2.run()
            for ref_mem2 in reference_kernel2(mem2, {}):
                pass
            vp = ref_mem2[6]
            if machine2.mem[vp:vp + len(inp2.values)] != ref_mem2[vp:vp + len(inp2.values)]:
                all_correct = False
                print("  INCORRECT on a random seed!")
                break
        print(f"All 8 seeds correct: {all_correct}")

test_relaxed()
