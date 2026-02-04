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
    def __init__(self, emit_debug: bool = False):
        self.instrs = []
        self.scratch = {}
        self.scratch_debug = {}
        self.scratch_ptr = 0
        self.const_map = {}
        self.emit_debug = emit_debug

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

        ready_heap = []
        for i in range(n_ops):
            if strict_pred_count[i] == 0 and weak_pred_count[i] == 0:
                heapq.heappush(ready_heap, i)

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
                i = heapq.heappop(ready_heap)
                if scheduled[i]:
                    continue

                if max_strict_pred_cycle[i] + 1 > cycle:
                    deferred.append(i)
                    continue
                if max_weak_pred_cycle[i] > cycle:
                    deferred.append(i)
                    continue

                engine, slot_list, _, _, slot_count = ops[i]
                if engine_counts[engine] + slot_count > SLOT_LIMITS[engine]:
                    deferred.append(i)
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
                        heapq.heappush(ready_heap, succ)

                for succ in weak_succs[i]:
                    weak_pred_count[succ] -= 1
                    if max_weak_pred_cycle[succ] < cycle:
                        max_weak_pred_cycle[succ] = cycle
                    if strict_pred_count[succ] == 0 and weak_pred_count[succ] == 0:
                        heapq.heappush(ready_heap, succ)

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
                instrs.extend(self._schedule_vliw(segment))
                segment = []
                instrs.append({engine: [slot]})
            else:
                segment.append((engine, slot))

        instrs.extend(self._schedule_vliw(segment))
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
            if op2 == "+" and op3 == "<<":
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
        # Scratch space addresses (header indices are fixed in build_mem_image)
        init_vars = [
            ("n_nodes", 1),
            ("forest_values_p", 4),
            ("inp_indices_p", 5),
            ("inp_values_p", 6),
        ]
        for name, _ in init_vars:
            self.alloc_scratch(name, 1)
        for name, header_idx in init_vars:
            self.add("load", ("const", tmp1, header_idx))
            self.add("load", ("load", self.scratch[name], tmp1))

        zero_const = self.scratch_const(0)
        one_const = self.scratch_const(1)
        two_const = self.scratch_const(2)
        batch_size_const = self.scratch_const(batch_size)

        vec_const_map = {}

        def alloc_vec_const(val, name=None):
            if val in vec_const_map:
                return vec_const_map[val]
            addr = self.alloc_scratch(name, length=VLEN)
            self.add("valu", ("vbroadcast", addr, self.scratch_const(val)))
            vec_const_map[val] = addr
            return addr

        vec_zero = alloc_vec_const(0, "vec_zero")
        vec_one = alloc_vec_const(1, "vec_one")
        vec_two = alloc_vec_const(2, "vec_two")

        for hi, (_, val1, op2, op3, val3) in enumerate(HASH_STAGES):
            alloc_vec_const(val1, f"hash_c1_{hi}")
            alloc_vec_const(val3, f"hash_c3_{hi}")
            if op2 == "+" and op3 == "<<":
                mul_val = 1 << val3
                if mul_val not in vec_const_map:
                    mul_const = self.alloc_scratch(f"hash_mul_{hi}", VLEN)
                    self.add(
                        "valu",
                        ("<<", mul_const, vec_one, vec_const_map[val3]),
                    )
                    vec_const_map[mul_val] = mul_const

        vec_n_nodes = self.alloc_scratch("vec_n_nodes", VLEN)
        self.add("valu", ("vbroadcast", vec_n_nodes, self.scratch["n_nodes"]))
        vec_forest_base = self.alloc_scratch("vec_forest_base", VLEN)
        self.add("valu", ("vbroadcast", vec_forest_base, self.scratch["forest_values_p"]))

        # Pause instructions are matched up with yield statements in the reference
        # kernel to let you debug at intermediate steps. The testing harness in this
        # file requires these match up to the reference kernel's yields, but the
        # submission harness ignores them.
        self.add("flow", ("pause",))
        # Any debug engine instruction is ignored by the submission simulator
        self.add("debug", ("comment", "Starting loop"))

        body = []  # array of slots

        # Scalar scratch registers (tail handling)
        tmp_idx = self.alloc_scratch("tmp_idx")
        tmp_val = self.alloc_scratch("tmp_val")
        tmp_node_val = self.alloc_scratch("tmp_node_val")
        tmp_addr = self.alloc_scratch("tmp_addr")

        interleave_groups = 8
        group_regs = []
        for g in range(interleave_groups):
            group_regs.append(
                {
                    "idx_ptr": self.alloc_scratch(f"idx_ptr_g{g}"),
                    "val_ptr": self.alloc_scratch(f"val_ptr_g{g}"),
                    "idx_ptr_next": self.alloc_scratch(f"idx_ptr_next_g{g}"),
                    "vec_idx": self.alloc_scratch(f"vec_idx_g{g}", VLEN),
                    "vec_val": self.alloc_scratch(f"vec_val_g{g}", VLEN),
                    "vec_node_val": self.alloc_scratch(f"vec_node_val_g{g}", VLEN),
                    "vec_addr": self.alloc_scratch(f"vec_addr_g{g}", VLEN),
                }
            )

        vec_count = (batch_size // VLEN) * VLEN
        vec_stride = VLEN * interleave_groups
        tail_idx_ptr = self.alloc_scratch("tail_idx_ptr")
        tail_val_ptr = self.alloc_scratch("tail_val_ptr")
        tail_idx_ptr_next = self.alloc_scratch("tail_idx_ptr_next")

        def emit_vector_group_ops(round, i, regs):
            keys = [(round, i + vi, "idx") for vi in range(VLEN)]

            idx_ptr = regs["idx_ptr"]
            val_ptr = regs["val_ptr"]
            idx_ptr_next = regs["idx_ptr_next"]
            vec_idx = regs["vec_idx"]
            vec_val = regs["vec_val"]
            vec_node_val = regs["vec_node_val"]
            vec_addr = regs["vec_addr"]
            vec_tmp1 = vec_addr
            vec_tmp2 = vec_node_val

            # idx = mem[inp_indices_p + i:i+VLEN]
            body.append(("load", ("vload", vec_idx, idx_ptr)))
            body.append(("debug", ("vcompare", vec_idx, keys)))
            # val = mem[inp_values_p + i:i+VLEN]
            body.append(("load", ("vload", vec_val, val_ptr)))
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
            # idx = 2*idx + (1 if val % 2 == 0 else 2)
            # => branch = (val & 1) + 1
            body.append(("valu", ("&", vec_tmp1, vec_val, vec_one)))
            body.append(("valu", ("+", vec_tmp2, vec_tmp1, vec_one)))
            body.append(("valu", ("*", vec_idx, vec_idx, vec_two)))
            body.append(("valu", ("+", vec_idx, vec_idx, vec_tmp2)))
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
            # idx = 0 if idx >= n_nodes else idx
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
            body.append(("flow", ("add_imm", idx_ptr_next, idx_ptr, vec_stride)))
            # mem[inp_indices_p + i] = idx
            body.append(("store", ("vstore", idx_ptr, vec_idx)))
            # mem[inp_values_p + i] = val
            body.append(("store", ("vstore", val_ptr, vec_val)))
            body.append(
                (
                    "alu",
                    [
                        ("+", idx_ptr, idx_ptr_next, zero_const),
                        ("+", val_ptr, idx_ptr_next, batch_size_const),
                    ],
                )
            )

        for round in range(rounds):
            for g, regs in enumerate(group_regs):
                offset = g * VLEN
                if offset == 0:
                    body.append(
                        (
                            "alu",
                            ("+", regs["idx_ptr"], self.scratch["inp_indices_p"], zero_const),
                        )
                    )
                    body.append(
                        (
                            "alu",
                            ("+", regs["val_ptr"], self.scratch["inp_values_p"], zero_const),
                        )
                    )
                else:
                    offset_const = self.scratch_const(offset)
                    body.append(
                        (
                            "alu",
                            ("+", regs["idx_ptr"], self.scratch["inp_indices_p"], offset_const),
                        )
                    )
                    body.append(
                        (
                            "alu",
                            ("+", regs["val_ptr"], self.scratch["inp_values_p"], offset_const),
                        )
                    )

            for base in range(0, vec_count, VLEN * interleave_groups):
                for g, regs in enumerate(group_regs):
                    i = base + g * VLEN
                    if i >= vec_count:
                        continue
                    emit_vector_group_ops(round, i, regs)

            if vec_count < batch_size:
                vec_count_const = self.scratch_const(vec_count)
                body.append(
                    ("alu", ("+", tail_idx_ptr, self.scratch["inp_indices_p"], vec_count_const))
                )
                body.append(
                    ("alu", ("+", tail_val_ptr, self.scratch["inp_values_p"], vec_count_const))
                )

            for i in range(vec_count, batch_size):
                # idx = mem[inp_indices_p + i]
                body.append(("load", ("load", tmp_idx, tail_idx_ptr)))
                body.append(("debug", ("compare", tmp_idx, (round, i, "idx"))))
                # val = mem[inp_values_p + i]
                body.append(("load", ("load", tmp_val, tail_val_ptr)))
                body.append(("debug", ("compare", tmp_val, (round, i, "val"))))
                # node_val = mem[forest_values_p + idx]
                body.append(("alu", ("+", tmp_addr, self.scratch["forest_values_p"], tmp_idx)))
                body.append(("load", ("load", tmp_node_val, tmp_addr)))
                body.append(("debug", ("compare", tmp_node_val, (round, i, "node_val"))))
                # val = myhash(val ^ node_val)
                body.append(("alu", ("^", tmp_val, tmp_val, tmp_node_val)))
                body.extend(self.build_hash(tmp_val, tmp1, tmp2, round, i))
                body.append(("debug", ("compare", tmp_val, (round, i, "hashed_val"))))
                # idx = 2*idx + (1 if val % 2 == 0 else 2)
                # => branch = (val & 1) + 1
                body.append(("alu", ("&", tmp1, tmp_val, one_const)))
                body.append(("alu", ("+", tmp3, tmp1, one_const)))
                body.append(("alu", ("*", tmp_idx, tmp_idx, two_const)))
                body.append(("alu", ("+", tmp_idx, tmp_idx, tmp3)))
                body.append(("debug", ("compare", tmp_idx, (round, i, "next_idx"))))
                # idx = 0 if idx >= n_nodes else idx
                body.append(("alu", ("<", tmp1, tmp_idx, self.scratch["n_nodes"])))
                body.append(("alu", ("*", tmp_idx, tmp_idx, tmp1)))
                body.append(("debug", ("compare", tmp_idx, (round, i, "wrapped_idx"))))
                body.append(("flow", ("add_imm", tail_idx_ptr_next, tail_idx_ptr, 1)))
                # mem[inp_indices_p + i] = idx
                body.append(("store", ("store", tail_idx_ptr, tmp_idx)))
                # mem[inp_values_p + i] = val
                body.append(("store", ("store", tail_val_ptr, tmp_val)))
                body.append(
                    (
                        "alu",
                        [
                            ("+", tail_idx_ptr, tail_idx_ptr_next, zero_const),
                            ("+", tail_val_ptr, tail_idx_ptr_next, batch_size_const),
                        ],
                    )
                )

        body_instrs = self.build(body, vliw=True)
        self.instrs.extend(body_instrs)
        # Required to match with the yield in reference_kernel2
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
