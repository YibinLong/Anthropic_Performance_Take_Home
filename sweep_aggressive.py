"""Try aggressive scheduler changes: WAR tracking modes, different priority formulas."""
import random
import sys
from copy import deepcopy
from collections import defaultdict
from problem import Tree, Input, build_mem_image, VLEN, N_CORES, Machine, SLOT_LIMITS, SCRATCH_SIZE
from perf_takehome import KernelBuilder, reference_kernel2
import heapq

def custom_schedule(kb, slots, succ_weight=512, fanout_weight=0, slot_weight=0,
                    war_mode="full", random_seed=None):
    """Custom scheduler with configurable options."""
    if not slots:
        return []

    ops = []
    for engine, slot in slots:
        if isinstance(slot, list):
            reads = set()
            writes = set()
            for subslot in slot:
                sr, sw = kb._slot_reads_writes(engine, subslot)
                reads.update(sr)
                writes.update(sw)
            slot_list = slot
            slot_count = len(slot)
        else:
            reads, writes = kb._slot_reads_writes(engine, slot)
            slot_list = [slot]
            slot_count = 1
        ops.append((engine, slot_list, reads, writes, slot_count))

    n_ops = len(ops)
    strict_succs = [set() for _ in range(n_ops)]
    weak_succs = [set() for _ in range(n_ops)]
    strict_pred_count = [0] * n_ops
    weak_pred_count = [0] * n_ops

    last_write = [-1] * SCRATCH_SIZE

    if war_mode == "full":
        readers_since_write = [[] for _ in range(SCRATCH_SIZE)]
    else:
        last_read = [-1] * SCRATCH_SIZE

    for i, (_, _, reads, writes, _) in enumerate(ops):
        for addr in reads:
            lw = last_write[addr]
            if lw != -1 and i not in strict_succs[lw]:
                strict_succs[lw].add(i)
                strict_pred_count[i] += 1
            if war_mode == "full":
                readers_since_write[addr].append(i)
            else:
                last_read[addr] = i
        for addr in writes:
            lw = last_write[addr]
            if lw != -1 and i not in strict_succs[lw]:
                strict_succs[lw].add(i)
                strict_pred_count[i] += 1
            if war_mode == "full":
                for lr in readers_since_write[addr]:
                    if lr != i and i not in weak_succs[lr]:
                        weak_succs[lr].add(i)
                        weak_pred_count[i] += 1
                readers_since_write[addr] = []
            else:
                lr = last_read[addr]
                if lr != -1 and lr != i and i not in weak_succs[lr]:
                    weak_succs[lr].add(i)
                    weak_pred_count[i] += 1
            last_write[addr] = i

    # Critical path
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

    # Priority
    op_priority = [0] * n_ops
    for i, (engine, _, _, _, sc) in enumerate(ops):
        succ_count = len(strict_succs[i]) + len(weak_succs[i])
        # Fanout: count of ops transitively unblocked (depth 2)
        fanout = succ_count
        if fanout_weight > 0:
            for s in strict_succs[i]:
                fanout += len(strict_succs[s])
        op_priority[i] = (
            crit_path[i] * 1024
            + succ_count * succ_weight
            + fanout * fanout_weight
            + sc * slot_weight
        )

    if random_seed is not None:
        rng = random.Random(random_seed)
        for i in range(n_ops):
            op_priority[i] += rng.randint(0, 256)

    # Schedule
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


def measure_custom(sched_kwargs, split=True, seed=123):
    """Build kernel, extract body slots, schedule with custom scheduler."""
    random.seed(seed)
    forest = Tree.generate(10)
    inp = Input.generate(forest, 256, 16)
    mem = build_mem_image(forest, inp)

    kb = KernelBuilder(split_hash_pairs=split)
    kb.build_kernel(forest.height, len(forest.values), len(inp.indices), 16)

    # Re-build body slots for custom scheduling
    # Reset and rebuild
    random.seed(seed)
    kb2 = KernelBuilder(split_hash_pairs=split)
    # Build and capture the body slots before VLIW scheduling
    # We need to intercept the build method...
    # Actually let's just use the built-in parameters
    pass

    # For simplicity, let's just use the built-in scheduler with different params
    random.seed(seed)
    kwargs = {"split_hash_pairs": split}
    kwargs.update(sched_kwargs)
    kb3 = KernelBuilder(**kwargs)
    kb3.build_kernel(forest.height, len(forest.values), len(inp.indices), 16)
    machine = Machine(mem, kb3.instrs, kb3.debug_info(), n_cores=N_CORES, value_trace={}, trace=False)
    machine.prints = False
    machine.run()
    for ref_mem in reference_kernel2(mem, {}):
        pass
    inp_values_p = ref_mem[6]
    if machine.mem[inp_values_p:inp_values_p + len(inp.values)] != ref_mem[inp_values_p:inp_values_p + len(inp.values)]:
        return None
    return machine.cycle


if __name__ == "__main__":
    best = 99999
    best_cfg = ""

    # Test the best config with wider range of succ+crit combos
    print("=== Fine-tuned combos ===")
    for cw in [768, 1024, 1280, 1536]:
        for sw in [384, 448, 512, 576, 640]:
            c = measure_custom({"scheduler_crit_weight": cw, "scheduler_succ_weight": sw})
            marker = " ***" if c and c < best else ""
            if c and c < best:
                best = c
                best_cfg = f"crit={cw}_succ={sw}"
            if c and c <= 1430:
                print(f"  crit={cw} succ={sw}: {c}{marker}")

    # Try with random perturbation on top of best
    print(f"\n=== Best combo + random restarts ===")
    for seed in range(100):
        c = measure_custom({"scheduler_crit_weight": 1024, "scheduler_succ_weight": 512, "scheduler_random_seed": seed})
        marker = " ***" if c and c < best else ""
        if c and c < best:
            best = c
            best_cfg = f"crit=1024_succ=512_seed={seed}"
        if c and c < 1430:
            print(f"  seed={seed}: {c}{marker}")

    print(f"\nBest: {best} ({best_cfg})")
