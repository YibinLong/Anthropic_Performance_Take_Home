"""
# Anthropic's Original Performance Engineering Take-home (Release version)

Copyright Anthropic PBC 2026. Permission is granted to modify and use, but not
to publish or redistribute your solutions so it's hard to find spoilers.

# Task

- Optimize the kernel (in KernelBuilder.build_kernel) as much as possible in the
  available time, as measured by test_kernel_cycles on a frozen separate copy
  of the simulator.

Validate your results using `python tests/submission_tests.py` without modifying
anything in the tests/ folder.

We recommend you look through problem.py next.
"""

from collections import defaultdict
import random
import unittest

from problem import (
    Engine,
    DebugInfo,
    SLOT_LIMITS,
    VLEN,
    N_CORES,
    SCRATCH_SIZE,
    Machine,
    Tree,
    Input,
    HASH_STAGES,
    reference_kernel,
    build_mem_image,
    reference_kernel2,
)


def analyze_utilization(instrs, slot_limits=SLOT_LIMITS, include_debug=False):
    engines = [engine for engine in slot_limits if engine != "debug"]
    totals = {engine: 0 for engine in engines}
    mins = {engine: None for engine in engines}
    maxs = {engine: 0 for engine in engines}
    cycle_count = 0

    for instr in instrs:
        has_non_debug = any(name != "debug" for name in instr.keys())
        if not has_non_debug and not include_debug:
            continue
        cycle_count += 1
        for engine in engines:
            count = len(instr.get(engine, []))
            totals[engine] += count
            if mins[engine] is None or count < mins[engine]:
                mins[engine] = count
            if count > maxs[engine]:
                maxs[engine] = count

    stats = {"cycle_count": cycle_count, "engines": {}}
    for engine in engines:
        avg = totals[engine] / cycle_count if cycle_count else 0
        util_pct = (avg / slot_limits[engine] * 100) if cycle_count else 0
        stats["engines"][engine] = {
            "total": totals[engine],
            "avg": avg,
            "min": mins[engine] if mins[engine] is not None else 0,
            "max": maxs[engine],
            "util_pct": util_pct,
            "limit": slot_limits[engine],
        }
    return stats


def format_utilization(stats):
    lines = [f"Slot utilization over {stats['cycle_count']} cycles:"]
    for engine in (engine for engine in SLOT_LIMITS if engine != "debug"):
        data = stats["engines"][engine]
        lines.append(
            f"{engine}: avg {data['avg']:.2f}/{data['limit']} "
            f"({data['util_pct']:.1f}%), min {data['min']}, max {data['max']}"
        )
    return "\n".join(lines)


def print_utilization(instrs, include_debug=False):
    stats = analyze_utilization(instrs, include_debug=include_debug)
    print(format_utilization(stats))


class KernelBuilder:
    def __init__(
        self,
        emit_debug: bool = False,
        interleave_groups: int = 26,
        interleave_groups_early: int | None = None,
    ):
        self.instrs = []
        self.scratch = {}
        self.scratch_debug = {}
        self.scratch_ptr = 0
        self.const_map = {}
        self.emit_debug = emit_debug
        self.interleave_groups = interleave_groups
        self.interleave_groups_early = (
            interleave_groups if interleave_groups_early is None else interleave_groups_early
        )

    def debug_info(self):
        return DebugInfo(scratch_map=self.scratch_debug)

    def _slot_reads_writes(self, engine, slot):
        reads = set()
        writes = set()

        def add_range(base, length):
            for i in range(length):
                writes.add(base + i)

        def add_read_range(base, length):
            for i in range(length):
                reads.add(base + i)

        if engine == "alu":
            _, dest, a1, a2 = slot
            reads.update([a1, a2])
            writes.add(dest)
        elif engine == "valu":
            match slot:
                case ("vbroadcast", dest, src):
                    reads.add(src)
                    add_range(dest, VLEN)
                case ("multiply_add", dest, a, b, c):
                    add_read_range(a, VLEN)
                    add_read_range(b, VLEN)
                    add_read_range(c, VLEN)
                    add_range(dest, VLEN)
                case (_, dest, a1, a2):
                    add_read_range(a1, VLEN)
                    add_read_range(a2, VLEN)
                    add_range(dest, VLEN)
        elif engine == "load":
            match slot:
                case ("load", dest, addr):
                    reads.add(addr)
                    writes.add(dest)
                case ("load_offset", dest, addr, offset):
                    reads.add(addr + offset)
                    writes.add(dest + offset)
                case ("vload", dest, addr):
                    reads.add(addr)
                    add_range(dest, VLEN)
                case ("const", dest, _):
                    writes.add(dest)
        elif engine == "store":
            match slot:
                case ("store", addr, src):
                    reads.update([addr, src])
                case ("vstore", addr, src):
                    reads.add(addr)
                    add_read_range(src, VLEN)
        elif engine == "flow":
            match slot:
                case ("select", dest, cond, a, b):
                    reads.update([cond, a, b])
                    writes.add(dest)
                case ("add_imm", dest, a, _):
                    reads.add(a)
                    writes.add(dest)
                case ("vselect", dest, cond, a, b):
                    add_read_range(cond, VLEN)
                    add_read_range(a, VLEN)
                    add_read_range(b, VLEN)
                    add_range(dest, VLEN)
                case ("halt",):
                    pass
                case ("pause",):
                    pass
                case ("trace_write", val):
                    reads.add(val)
                case ("cond_jump", cond, _):
                    reads.add(cond)
                case ("cond_jump_rel", cond, _):
                    reads.add(cond)
                case ("jump", _):
                    pass
                case ("jump_indirect", addr):
                    reads.add(addr)
                case ("coreid", dest):
                    writes.add(dest)
        elif engine == "debug":
            match slot:
                case ("compare", loc, _):
                    reads.add(loc)
                case ("vcompare", loc, _):
                    add_read_range(loc, VLEN)
                case ("comment", _):
                    pass

        return reads, writes

    def _is_barrier(self, engine: Engine, slot: tuple) -> bool:
        if engine != "flow":
            return False
        return slot[0] in {
            "halt",
            "pause",
            "cond_jump",
            "cond_jump_rel",
            "jump",
            "jump_indirect",
        }

    def _slot_side_effect(self, engine: Engine, slot: tuple) -> bool:
        if engine == "store":
            return True
        if engine == "flow":
            return True
        if engine == "debug":
            return self.emit_debug
        return False

    def _optimize_slots(self, slots: list[tuple[Engine, tuple]]):
        if not slots:
            return []

        live = set()
        optimized = []

        for engine, slot in reversed(slots):
            if isinstance(slot, list):
                kept = []
                reads_all = set()
                writes_all = set()
                for subslot in slot:
                    reads, writes = self._slot_reads_writes(engine, subslot)
                    side_effect = self._slot_side_effect(engine, subslot)
                    if side_effect or (writes & live):
                        kept.append(subslot)
                        reads_all.update(reads)
                        writes_all.update(writes)
                if not kept:
                    continue
                live.difference_update(writes_all)
                live.update(reads_all)
                optimized.append((engine, kept))
            else:
                reads, writes = self._slot_reads_writes(engine, slot)
                side_effect = self._slot_side_effect(engine, slot)
                if side_effect or (writes & live):
                    live.difference_update(writes)
                    live.update(reads)
                    optimized.append((engine, slot))

        optimized.reverse()
        return optimized

    def _schedule_vliw(self, slots: list[tuple[Engine, tuple]]):
        if not slots:
            return []

        ops = []
        for engine, slot in slots:
            if isinstance(slot, list):
                reads = set()
                writes = set()
                for subslot in slot:
                    sub_reads, sub_writes = self._slot_reads_writes(engine, subslot)
                    reads.update(sub_reads)
                    writes.update(sub_writes)
                slot_list = slot
                slot_count = len(slot)
            else:
                reads, writes = self._slot_reads_writes(engine, slot)
                slot_list = [slot]
                slot_count = 1
            ops.append((engine, slot_list, reads, writes, slot_count))

        n_ops = len(ops)
        strict_succs = [set() for _ in range(n_ops)]
        weak_succs = [set() for _ in range(n_ops)]
        strict_pred_count = [0] * n_ops
        weak_pred_count = [0] * n_ops

        last_write = [-1] * SCRATCH_SIZE
        last_read = [-1] * SCRATCH_SIZE

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
                last_read[addr] = -1

        import heapq

        # Compute critical path length for each op (longest path to any terminal)
        # using reverse topological order
        crit_path = [1] * n_ops  # each op has at least length 1
        # Process in reverse topological order (reverse of original index order
        # works since dependencies only go forward)
        for i in range(n_ops - 1, -1, -1):
            max_succ = 0
            for s in strict_succs[i]:
                if crit_path[s] > max_succ:
                    max_succ = crit_path[s]
            for s in weak_succs[i]:
                if crit_path[s] > max_succ:
                    max_succ = crit_path[s]
            crit_path[i] = 1 + max_succ

        ready_heap = []
        for i in range(n_ops):
            if strict_pred_count[i] == 0 and weak_pred_count[i] == 0:
                heapq.heappush(ready_heap, (-crit_path[i], i))

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
                neg_cp, i = heapq.heappop(ready_heap)
                if scheduled[i]:
                    continue

                if max_strict_pred_cycle[i] + 1 > cycle:
                    deferred.append((-crit_path[i], i))
                    continue
                if max_weak_pred_cycle[i] > cycle:
                    deferred.append((-crit_path[i], i))
                    continue

                engine, slot_list, _, _, slot_count = ops[i]
                if engine_counts[engine] + slot_count > SLOT_LIMITS[engine]:
                    deferred.append((-crit_path[i], i))
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
                        heapq.heappush(ready_heap, (-crit_path[succ], succ))

                for succ in weak_succs[i]:
                    weak_pred_count[succ] -= 1
                    if max_weak_pred_cycle[succ] < cycle:
                        max_weak_pred_cycle[succ] = cycle
                    if strict_pred_count[succ] == 0 and weak_pred_count[succ] == 0:
                        heapq.heappush(ready_heap, (-crit_path[succ], succ))

            if not scheduled_any:
                raise RuntimeError("VLIW scheduler deadlock (no schedulable ops)")

            instrs.append(bundle)
            cycle += 1

            if deferred:
                heapq.heapify(deferred)
                ready_heap = deferred
            else:
                ready_heap = []

        return instrs

    def build(self, slots: list[tuple[Engine, tuple]], vliw: bool = False):
        # Simple slot packing that just uses one slot per instruction bundle
        if not vliw:
            instrs = []
            for engine, slot in slots:
                if isinstance(slot, list):
                    instrs.append({engine: slot})
                else:
                    instrs.append({engine: [slot]})
            return instrs

        if not self.emit_debug:
            slots = [(engine, slot) for engine, slot in slots if engine != "debug"]

        instrs = []
        segment = []
        for engine, slot in slots:
            if self._is_barrier(engine, slot):
                instrs.extend(self._schedule_vliw(self._optimize_slots(segment)))
                segment = []
                instrs.append({engine: [slot]})
            else:
                segment.append((engine, slot))

        instrs.extend(self._schedule_vliw(self._optimize_slots(segment)))
        return instrs

    def add(self, engine, slot):
        if engine == "debug" and not self.emit_debug:
            return
        self.instrs.append({engine: [slot]})

    def alloc_scratch(self, name=None, length=1):
        addr = self.scratch_ptr
        if name is not None:
            self.scratch[name] = addr
            self.scratch_debug[addr] = (name, length)
        self.scratch_ptr += length
        assert self.scratch_ptr <= SCRATCH_SIZE, "Out of scratch space"
        return addr

    def scratch_const(self, val, name=None):
        if val not in self.const_map:
            addr = self.alloc_scratch(name)
            self.add("load", ("const", addr, val))
            self.const_map[val] = addr
        return self.const_map[val]

    def build_hash(self, val_hash_addr, tmp1, tmp2, round, i):
        slots = []

        for hi, (op1, val1, op2, op3, val3) in enumerate(HASH_STAGES):
            slots.append(
                (
                    "alu",
                    [
                        (op1, tmp1, val_hash_addr, self.scratch_const(val1)),
                        (op3, tmp2, val_hash_addr, self.scratch_const(val3)),
                    ],
                )
            )
            slots.append(("alu", (op2, val_hash_addr, tmp1, tmp2)))
            slots.append(("debug", ("compare", val_hash_addr, (round, i, "hash_stage", hi))))

        return slots

    def build_hash_vec(self, val_hash_addr, tmp1, tmp2, round, i_base, vec_const_map):
        slots = []

        for hi, (op1, val1, op2, op3, val3) in enumerate(HASH_STAGES):
            if op1 == "+" and op2 == "+" and op3 == "<<":
                # Algebraic simplification: a*(1<<shift) + (a + const)
                # = a*((1<<shift)+1) + const → single multiply_add
                combined_mul = (1 << val3) + 1
                combined_mul_vec = vec_const_map[combined_mul]
                slots.append(
                    (
                        "valu",
                        ("multiply_add", val_hash_addr, val_hash_addr, combined_mul_vec, vec_const_map[val1]),
                    )
                )
            elif op2 == "+" and op3 == "<<":
                slots.append(
                    ("valu", (op1, tmp1, val_hash_addr, vec_const_map[val1]))
                )
                mul_const = vec_const_map[1 << val3]
                slots.append(
                    (
                        "valu",
                        ("multiply_add", val_hash_addr, val_hash_addr, mul_const, tmp1),
                    )
                )
            else:
                slots.append(
                    (
                        "valu",
                        [
                            (op1, tmp1, val_hash_addr, vec_const_map[val1]),
                            (op3, tmp2, val_hash_addr, vec_const_map[val3]),
                        ],
                    )
                )
                slots.append(("valu", (op2, val_hash_addr, tmp1, tmp2)))
            slots.append(
                (
                    "debug",
                    (
                        "vcompare",
                        val_hash_addr,
                        [
                            (round, i_base + vi, "hash_stage", hi)
                            for vi in range(VLEN)
                        ],
                    ),
                )
            )

        return slots

    def build_kernel(
        self, forest_height: int, n_nodes: int, batch_size: int, rounds: int
    ):
        """
        Like reference_kernel2 but building actual instructions.
        Vectorized inner loop using SIMD VALU + gather via load_offset.
        """
        tmp1 = self.alloc_scratch("tmp1")
        tmp2 = self.alloc_scratch("tmp2")
        tmp3 = self.alloc_scratch("tmp3")

        header = []  # collect header ops for VLIW scheduling

        # Scratch space addresses (header indices are fixed in build_mem_image)
        init_vars = [
            ("n_nodes", 1),
            ("forest_values_p", 4),
            ("inp_indices_p", 5),
            ("inp_values_p", 6),
        ]
        # Use separate tmp addresses for each header load to avoid WAW serialization
        header_tmp_addrs = []
        for name, _ in init_vars:
            self.alloc_scratch(name, 1)
            header_tmp_addrs.append(self.alloc_scratch())
        for idx_i, (name, header_idx) in enumerate(init_vars):
            htmp = header_tmp_addrs[idx_i]
            header.append(("load", ("const", htmp, header_idx)))
            header.append(("load", ("load", self.scratch[name], htmp)))

        # scratch_const replacement for header: allocate and emit to header list
        def header_scratch_const(val, name=None):
            if val not in self.const_map:
                addr = self.alloc_scratch(name)
                self.const_map[val] = addr
                header.append(("load", ("const", addr, val)))
            return self.const_map[val]

        zero_const = header_scratch_const(0)
        one_const = header_scratch_const(1)
        two_const = header_scratch_const(2)

        vec_const_map = {}

        def alloc_vec_const(val, name=None):
            if val in vec_const_map:
                return vec_const_map[val]
            addr = self.alloc_scratch(name, length=VLEN)
            scalar_addr = header_scratch_const(val)
            header.append(("valu", ("vbroadcast", addr, scalar_addr)))
            vec_const_map[val] = addr
            return addr

        vec_zero = alloc_vec_const(0, "vec_zero")
        vec_one = alloc_vec_const(1, "vec_one")
        vec_two = alloc_vec_const(2, "vec_two")
        vec_three = alloc_vec_const(3, "vec_three")

        for hi, (op1, val1, op2, op3, val3) in enumerate(HASH_STAGES):
            alloc_vec_const(val1, f"hash_c1_{hi}")
            alloc_vec_const(val3, f"hash_c3_{hi}")
            if op2 == "+" and op3 == "<<":
                if op1 == "+":
                    # Algebraic simplification: a*(1<<shift) + (a + const)
                    # = a*((1<<shift)+1) + const → single multiply_add
                    combined_mul = (1 << val3) + 1
                    alloc_vec_const(combined_mul, f"hash_combined_mul_{hi}")
                else:
                    mul_val = 1 << val3
                    if mul_val not in vec_const_map:
                        mul_const = self.alloc_scratch(f"hash_mul_{hi}", VLEN)
                        header.append(
                            ("valu",
                            ("<<", mul_const, vec_one, vec_const_map[val3]))
                        )
                        vec_const_map[mul_val] = mul_const

        vec_n_nodes = self.alloc_scratch("vec_n_nodes", VLEN)
        header.append(("valu", ("vbroadcast", vec_n_nodes, self.scratch["n_nodes"])))
        vec_forest_base = self.alloc_scratch("vec_forest_base", VLEN)
        header.append(("valu", ("vbroadcast", vec_forest_base, self.scratch["forest_values_p"])))
        node0 = self.alloc_scratch("node0")
        node1 = self.alloc_scratch("node1")
        node2 = self.alloc_scratch("node2")
        node3 = self.alloc_scratch("node3")
        node4 = self.alloc_scratch("node4")
        node5 = self.alloc_scratch("node5")
        node6 = self.alloc_scratch("node6")
        node_addrs = [self.alloc_scratch() for _ in range(6)]
        header.append(("load", ("load", node0, self.scratch["forest_values_p"])))
        header.append(("alu", ("+", node_addrs[0], self.scratch["forest_values_p"], one_const)))
        header.append(("alu", ("+", node_addrs[1], self.scratch["forest_values_p"], two_const)))
        header.append(("alu", ("+", node_addrs[2], self.scratch["forest_values_p"], header_scratch_const(3))))
        header.append(("alu", ("+", node_addrs[3], self.scratch["forest_values_p"], header_scratch_const(4))))
        header.append(("alu", ("+", node_addrs[4], self.scratch["forest_values_p"], header_scratch_const(5))))
        header.append(("alu", ("+", node_addrs[5], self.scratch["forest_values_p"], header_scratch_const(6))))
        header.append(("load", ("load", node1, node_addrs[0])))
        header.append(("load", ("load", node2, node_addrs[1])))
        header.append(("load", ("load", node3, node_addrs[2])))
        header.append(("load", ("load", node4, node_addrs[3])))
        header.append(("load", ("load", node5, node_addrs[4])))
        header.append(("load", ("load", node6, node_addrs[5])))
        vec_node0 = self.alloc_scratch("vec_node0", VLEN)
        vec_node1 = self.alloc_scratch("vec_node1", VLEN)
        vec_node2 = self.alloc_scratch("vec_node2", VLEN)
        vec_node3 = self.alloc_scratch("vec_node3", VLEN)
        vec_node4 = self.alloc_scratch("vec_node4", VLEN)
        vec_node5 = self.alloc_scratch("vec_node5", VLEN)
        vec_node6 = self.alloc_scratch("vec_node6", VLEN)
        header.append(("valu", ("vbroadcast", vec_node0, node0)))
        header.append(("valu", ("vbroadcast", vec_node1, node1)))
        header.append(("valu", ("vbroadcast", vec_node2, node2)))
        header.append(("valu", ("vbroadcast", vec_node3, node3)))
        header.append(("valu", ("vbroadcast", vec_node4, node4)))
        header.append(("valu", ("vbroadcast", vec_node5, node5)))
        header.append(("valu", ("vbroadcast", vec_node6, node6)))
        vec_node21_diff = self.alloc_scratch("vec_node_diff_2_1", VLEN)
        vec_node43_diff = self.alloc_scratch("vec_node_diff_4_3", VLEN)
        vec_node65_diff = self.alloc_scratch("vec_node_diff_6_5", VLEN)
        vec_node1_minus_diff = self.alloc_scratch("vec_node_1_minus_diff_21", VLEN)
        vec_node53_diff = self.alloc_scratch("vec_node_diff_5_3", VLEN)
        vec_node6543_diff = self.alloc_scratch("vec_node_diff_65_43", VLEN)
        header.append(("valu", ("-", vec_node21_diff, vec_node2, vec_node1)))
        header.append(("valu", ("-", vec_node43_diff, vec_node4, vec_node3)))
        header.append(("valu", ("-", vec_node65_diff, vec_node6, vec_node5)))
        header.append(("valu", ("-", vec_node1_minus_diff, vec_node1, vec_node21_diff)))
        header.append(("valu", ("-", vec_node53_diff, vec_node5, vec_node3)))
        header.append(("valu", ("-", vec_node6543_diff, vec_node65_diff, vec_node43_diff)))
        idx_arr = self.alloc_scratch("idx_arr", batch_size)
        val_arr = self.alloc_scratch("val_arr", batch_size)

        # Pause instructions are matched up with yield statements in the reference
        # kernel to let you debug at intermediate steps. The testing harness in this
        # file requires these match up to the reference kernel's yields, but the
        # submission harness ignores them.
        if self.emit_debug:
            # Schedule header separately before the pause barrier
            header_instrs = self.build(header, vliw=True)
            self.instrs.extend(header_instrs)
            self.instrs.append({"flow": [("pause",)]})
        # Any debug engine instruction is ignored by the submission simulator
        self.add("debug", ("comment", "Starting loop"))

        # In non-debug mode, merge header into body for joint VLIW scheduling
        body = list(header) if not self.emit_debug else []

        # Scalar scratch registers (tail handling)
        tmp_node_val = self.alloc_scratch("tmp_node_val")
        tmp_addr = self.alloc_scratch("tmp_addr")
        tmp_addr_b = self.alloc_scratch("tmp_addr_b")

        interleave_groups = self.interleave_groups
        interleave_groups_early = self.interleave_groups_early
        max_groups = max(interleave_groups, interleave_groups_early)
        group_regs = []
        for g in range(max_groups):
            group_regs.append(
                {
                    "vec_node_val": self.alloc_scratch(f"vec_node_val_g{g}", VLEN),
                    "vec_addr": self.alloc_scratch(f"vec_addr_g{g}", VLEN),
                    "vec_val_save": self.alloc_scratch(f"vec_val_save_g{g}", VLEN),
                }
            )

        vec_count = (batch_size // VLEN) * VLEN

        def emit_vector_group_ops(round, i, regs, depth):
            keys = [(round, i + vi, "idx") for vi in range(VLEN)]

            vec_idx = idx_arr + i
            vec_val = val_arr + i
            vec_node_val = regs["vec_node_val"]
            vec_addr = regs["vec_addr"]
            vec_val_save = regs["vec_val_save"]
            vec_tmp1 = vec_addr
            vec_tmp2 = vec_node_val

            body.append(("debug", ("vcompare", vec_idx, keys)))
            body.append(
                (
                    "debug",
                    (
                        "vcompare",
                        vec_val,
                        [(round, i + vi, "val") for vi in range(VLEN)],
                    ),
                )
            )
            if depth == 0:
                body.append(
                    (
                        "debug",
                        (
                            "vcompare",
                            vec_node0,
                            [(round, i + vi, "node_val") for vi in range(VLEN)],
                        ),
                    )
                )
                # val = myhash(val ^ node_val)
                body.append(("valu", ("^", vec_val, vec_val, vec_node0)))
                body.extend(
                    self.build_hash_vec(
                        vec_val, vec_tmp1, vec_tmp2, round, i, vec_const_map
                    )
                )
            elif depth == 1:
                # node_val = node1 + (idx - 1) * (node2 - node1)
                body.append(
                    ("valu", ("multiply_add", vec_node_val, vec_idx, vec_node21_diff, vec_node1_minus_diff))
                )
                body.append(
                    (
                        "debug",
                        (
                            "vcompare",
                            vec_node_val,
                            [(round, i + vi, "node_val") for vi in range(VLEN)],
                        ),
                    )
                )
                # val = myhash(val ^ node_val)
                body.append(("valu", ("^", vec_val, vec_val, vec_node_val)))
                body.extend(
                    self.build_hash_vec(
                        vec_val, vec_tmp1, vec_tmp2, round, i, vec_const_map
                    )
                )
            elif depth == 2:
                # node_val from nodes 3..6 using idx in [3, 6]
                body.append(("valu", ("-", vec_addr, vec_idx, vec_three)))  # path
                body.append(("valu", ("&", vec_val_save, vec_addr, vec_one)))  # b0
                body.append(("valu", (">>", vec_node_val, vec_addr, vec_one)))  # b1
                body.append(
                    ("valu", ("multiply_add", vec_addr, vec_val_save, vec_node43_diff, vec_node3))
                )  # v01
                body.append(
                    ("valu", ("multiply_add", vec_val_save, vec_val_save, vec_node6543_diff, vec_node53_diff))
                )  # diff
                body.append(
                    ("valu", ("multiply_add", vec_node_val, vec_node_val, vec_val_save, vec_addr))
                )  # node_val
                body.append(
                    (
                        "debug",
                        (
                            "vcompare",
                            vec_node_val,
                            [(round, i + vi, "node_val") for vi in range(VLEN)],
                        ),
                    )
                )
                # val = myhash(val ^ node_val)
                body.append(("valu", ("^", vec_val, vec_val, vec_node_val)))
                body.extend(
                    self.build_hash_vec(
                        vec_val, vec_tmp1, vec_tmp2, round, i, vec_const_map
                    )
                )
            else:
                # node_val = mem[forest_values_p + idx] (gather)
                body.append(("valu", ("+", vec_addr, vec_forest_base, vec_idx)))
                for offset in range(VLEN):
                    body.append(("load", ("load_offset", vec_node_val, vec_addr, offset)))
                body.append(
                    (
                        "debug",
                        (
                            "vcompare",
                            vec_node_val,
                            [(round, i + vi, "node_val") for vi in range(VLEN)],
                        ),
                    )
                )
                # val = myhash(val ^ node_val)
                body.append(("valu", ("^", vec_val, vec_val, vec_node_val)))
                body.extend(
                    self.build_hash_vec(
                        vec_val, vec_tmp1, vec_tmp2, round, i, vec_const_map
                    )
                )
            body.append(
                (
                    "debug",
                    (
                        "vcompare",
                        vec_val,
                        [(round, i + vi, "hashed_val") for vi in range(VLEN)],
                    ),
                )
            )
            # idx update:
            # - depth 0: idx is always 0 before update, so we can write branch directly
            # - depth == forest_height: next round (depth 0) overwrites idx, so we can skip the update
            if depth == forest_height and not self.emit_debug:
                return

            # idx = 2*idx + (1 if val % 2 == 0 else 2)
            # => branch = (val & 1) + 1
            if depth == 0:
                body.append(("valu", ("&", vec_idx, vec_val, vec_one)))
                body.append(("valu", ("+", vec_idx, vec_idx, vec_one)))
            else:
                body.append(("valu", ("&", vec_tmp1, vec_val, vec_one)))
                body.append(("valu", ("+", vec_tmp2, vec_tmp1, vec_one)))
                body.append(
                    ("valu", ("multiply_add", vec_idx, vec_idx, vec_two, vec_tmp2))
                )
            body.append(
                (
                    "debug",
                    (
                        "vcompare",
                        vec_idx,
                        [(round, i + vi, "next_idx") for vi in range(VLEN)],
                    ),
                )
            )
            # idx = 0 if idx >= n_nodes else idx (only needed at wrap depth)
            if depth == forest_height:
                body.append(("valu", ("<", vec_tmp1, vec_idx, vec_n_nodes)))
                body.append(("valu", ("*", vec_idx, vec_idx, vec_tmp1)))
                body.append(
                    (
                        "debug",
                        (
                            "vcompare",
                            vec_idx,
                            [(round, i + vi, "wrapped_idx") for vi in range(VLEN)],
                        ),
                    )
                )
            else:
                body.append(
                    (
                        "debug",
                        (
                            "vcompare",
                            vec_idx,
                            [(round, i + vi, "wrapped_idx") for vi in range(VLEN)],
                        ),
                    )
                )

        # Pre-allocate offset constant scratch addresses and emit loads into body
        # so VLIW scheduler can pair them (instead of single-load cycles via self.add)
        offset_addrs = {}
        all_offsets = set()
        for base in range(0, vec_count, VLEN):
            all_offsets.add(base)
        for i in range(vec_count, batch_size):
            all_offsets.add(i)
        for off in sorted(all_offsets):
            if off not in self.const_map:
                addr = self.alloc_scratch()
                self.const_map[off] = addr
            offset_addrs[off] = self.const_map[off]
            body.append(("load", ("const", offset_addrs[off], off)))

        for base in range(0, vec_count, VLEN):
            body.append(
                ("alu", ("+", tmp_addr, self.scratch["inp_indices_p"], offset_addrs[base]))
            )
            body.append(
                ("alu", ("+", tmp_addr_b, self.scratch["inp_values_p"], offset_addrs[base]))
            )
            body.append(("load", ("vload", idx_arr + base, tmp_addr)))
            body.append(("load", ("vload", val_arr + base, tmp_addr_b)))

        for i in range(vec_count, batch_size):
            body.append(
                ("alu", ("+", tmp_addr, self.scratch["inp_indices_p"], offset_addrs[i]))
            )
            body.append(
                ("alu", ("+", tmp_addr_b, self.scratch["inp_values_p"], offset_addrs[i]))
            )
            body.append(("load", ("load", idx_arr + i, tmp_addr)))
            body.append(("load", ("load", val_arr + i, tmp_addr_b)))

        for round in range(rounds):
            depth = round % (forest_height + 1)
            regs_list = (
                group_regs[:interleave_groups_early]
                if depth <= 2
                else group_regs[:interleave_groups]
            )
            for base in range(0, vec_count, VLEN * len(regs_list)):
                for g, regs in enumerate(regs_list):
                    i = base + g * VLEN
                    if i >= vec_count:
                        continue
                    emit_vector_group_ops(round, i, regs, depth)

            for i in range(vec_count, batch_size):
                idx_addr = idx_arr + i
                val_addr = val_arr + i
                body.append(("debug", ("compare", idx_addr, (round, i, "idx"))))
                body.append(("debug", ("compare", val_addr, (round, i, "val"))))
                # node_val = mem[forest_values_p + idx]
                body.append(("alu", ("+", tmp_addr, self.scratch["forest_values_p"], idx_addr)))
                body.append(("load", ("load", tmp_node_val, tmp_addr)))
                body.append(("debug", ("compare", tmp_node_val, (round, i, "node_val"))))
                # val = myhash(val ^ node_val)
                body.append(("alu", ("^", val_addr, val_addr, tmp_node_val)))
                body.extend(self.build_hash(val_addr, tmp1, tmp2, round, i))
                body.append(("debug", ("compare", val_addr, (round, i, "hashed_val"))))
                # idx update
                if depth == forest_height and not self.emit_debug:
                    continue

                # idx = 2*idx + (1 if val % 2 == 0 else 2)
                # => branch = (val & 1) + 1
                if depth == 0:
                    body.append(("alu", ("&", idx_addr, val_addr, one_const)))
                    body.append(("alu", ("+", idx_addr, idx_addr, one_const)))
                else:
                    body.append(("alu", ("&", tmp1, val_addr, one_const)))
                    body.append(("alu", ("+", tmp3, tmp1, one_const)))
                    body.append(("alu", ("<<", idx_addr, idx_addr, one_const)))
                    body.append(("alu", ("+", idx_addr, idx_addr, tmp3)))
                body.append(("debug", ("compare", idx_addr, (round, i, "next_idx"))))
                # idx = 0 if idx >= n_nodes else idx
                body.append(("alu", ("<", tmp1, idx_addr, self.scratch["n_nodes"])))
                body.append(("alu", ("*", idx_addr, idx_addr, tmp1)))
                body.append(("debug", ("compare", idx_addr, (round, i, "wrapped_idx"))))

        for base in range(0, vec_count, VLEN):
            body.append(
                ("alu", ("+", tmp_addr, self.scratch["inp_indices_p"], offset_addrs[base]))
            )
            body.append(
                ("alu", ("+", tmp_addr_b, self.scratch["inp_values_p"], offset_addrs[base]))
            )
            body.append(("store", ("vstore", tmp_addr, idx_arr + base)))
            body.append(("store", ("vstore", tmp_addr_b, val_arr + base)))

        for i in range(vec_count, batch_size):
            body.append(
                ("alu", ("+", tmp_addr, self.scratch["inp_indices_p"], offset_addrs[i]))
            )
            body.append(
                ("alu", ("+", tmp_addr_b, self.scratch["inp_values_p"], offset_addrs[i]))
            )
            body.append(("store", ("store", tmp_addr, idx_arr + i)))
            body.append(("store", ("store", tmp_addr_b, val_arr + i)))

        body_instrs = self.build(body, vliw=True)
        self.instrs.extend(body_instrs)
        # Required to match with the yield in reference_kernel2
        if self.emit_debug:
            self.instrs.append({"flow": [("pause",)]})

BASELINE = 147734

def do_kernel_test(
    forest_height: int,
    rounds: int,
    batch_size: int,
    seed: int = 123,
    trace: bool = False,
    prints: bool = False,
    utilization: bool = False,
):
    print(f"{forest_height=}, {rounds=}, {batch_size=}")
    random.seed(seed)
    forest = Tree.generate(forest_height)
    inp = Input.generate(forest, batch_size, rounds)
    mem = build_mem_image(forest, inp)

    kb = KernelBuilder()
    kb.build_kernel(forest.height, len(forest.values), len(inp.indices), rounds)
    # print(kb.instrs)
    if utilization:
        print_utilization(kb.instrs)

    value_trace = {}
    machine = Machine(
        mem,
        kb.instrs,
        kb.debug_info(),
        n_cores=N_CORES,
        value_trace=value_trace,
        trace=trace,
    )
    machine.prints = prints
    for i, ref_mem in enumerate(reference_kernel2(mem, value_trace)):
        machine.run()
        inp_values_p = ref_mem[6]
        if prints:
            print(machine.mem[inp_values_p : inp_values_p + len(inp.values)])
            print(ref_mem[inp_values_p : inp_values_p + len(inp.values)])
        assert (
            machine.mem[inp_values_p : inp_values_p + len(inp.values)]
            == ref_mem[inp_values_p : inp_values_p + len(inp.values)]
        ), f"Incorrect result on round {i}"
        inp_indices_p = ref_mem[5]
        if prints:
            print(machine.mem[inp_indices_p : inp_indices_p + len(inp.indices)])
            print(ref_mem[inp_indices_p : inp_indices_p + len(inp.indices)])
        # Updating these in memory isn't required, but you can enable this check for debugging
        # assert machine.mem[inp_indices_p:inp_indices_p+len(inp.indices)] == ref_mem[inp_indices_p:inp_indices_p+len(inp.indices)]

    print("CYCLES: ", machine.cycle)
    print("Speedup over baseline: ", BASELINE / machine.cycle)
    return machine.cycle


class Tests(unittest.TestCase):
    def test_ref_kernels(self):
        """
        Test the reference kernels against each other
        """
        random.seed(123)
        for i in range(10):
            f = Tree.generate(4)
            inp = Input.generate(f, 10, 6)
            mem = build_mem_image(f, inp)
            reference_kernel(f, inp)
            for _ in reference_kernel2(mem, {}):
                pass
            assert inp.indices == mem[mem[5] : mem[5] + len(inp.indices)]
            assert inp.values == mem[mem[6] : mem[6] + len(inp.values)]

    def test_kernel_trace(self):
        # Full-scale example for performance testing
        do_kernel_test(10, 16, 256, trace=True, prints=False)

    # Passing this test is not required for submission, see submission_tests.py for the actual correctness test
    # You can uncomment this if you think it might help you debug
    # def test_kernel_correctness(self):
    #     for batch in range(1, 3):
    #         for forest_height in range(3):
    #             do_kernel_test(
    #                 forest_height + 2, forest_height + 4, batch * 16 * VLEN * N_CORES
    #             )

    def test_kernel_cycles(self):
        do_kernel_test(10, 16, 256)


# To run all the tests:
#    python perf_takehome.py
# To run a specific test:
#    python perf_takehome.py Tests.test_kernel_cycles
# To view a hot-reloading trace of all the instructions:  **Recommended debug loop**
# NOTE: The trace hot-reloading only works in Chrome. In the worst case if things aren't working, drag trace.json onto https://ui.perfetto.dev/
#    python perf_takehome.py Tests.test_kernel_trace
# Then run `python watch_trace.py` in another tab, it'll open a browser tab, then click "Open Perfetto"
# You can then keep that open and re-run the test to see a new trace.

# To run the proper checks to see which thresholds you pass:
#    python tests/submission_tests.py

if __name__ == "__main__":
    unittest.main()
