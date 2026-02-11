from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import json
import math
from typing import Any

from problem import SLOT_LIMITS


ENGINES = [engine for engine in SLOT_LIMITS if engine != "debug"]
BARRIER_FLOW_OPS = {
    "halt",
    "pause",
    "cond_jump",
    "cond_jump_rel",
    "jump",
    "jump_indirect",
}


def _percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    rank = (pct / 100.0) * (len(ordered) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(ordered[lo])
    frac = rank - lo
    return (ordered[lo] * (1.0 - frac)) + (ordered[hi] * frac)


def _has_non_debug(bundle: dict[str, list[tuple]]) -> bool:
    return any(engine != "debug" for engine in bundle.keys())


def _barrier_slots(bundle: dict[str, list[tuple]]) -> list[tuple]:
    barrier = []
    for slot in bundle.get("flow", []):
        if slot and slot[0] in BARRIER_FLOW_OPS:
            barrier.append(slot)
    return barrier


def split_non_debug_segments(
    instrs: list[dict[str, list[tuple]]],
    include_debug: bool = False,
) -> tuple[list[list[dict[str, list[tuple]]]], list[dict[str, Any]]]:
    segments: list[list[dict[str, list[tuple]]]] = []
    barriers: list[dict[str, Any]] = []
    current: list[dict[str, list[tuple]]] = []
    non_debug_cycle = 0

    for bundle_idx, bundle in enumerate(instrs):
        if not _has_non_debug(bundle) and not include_debug:
            continue
        trimmed = bundle if include_debug else {k: v for k, v in bundle.items() if k != "debug"}
        barriers_here = _barrier_slots(trimmed)
        if barriers_here:
            if current:
                segments.append(current)
                current = []
            barriers.append(
                {
                    "bundle_index": bundle_idx,
                    "non_debug_cycle": non_debug_cycle,
                    "slots": barriers_here,
                }
            )
        else:
            current.append(trimmed)
        non_debug_cycle += 1

    if current:
        segments.append(current)
    return segments, barriers


def _opcode_mix(segment_instrs: list[dict[str, list[tuple]]]) -> dict[str, dict[str, int]]:
    mix: dict[str, Counter[str]] = {engine: Counter() for engine in ENGINES}
    for bundle in segment_instrs:
        for engine in ENGINES:
            for slot in bundle.get(engine, []):
                opcode = slot[0] if slot else "unknown"
                mix[engine][opcode] += 1
    return {
        engine: dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))
        for engine, counter in mix.items()
        if counter
    }


def _flatten_top_opcodes(op_mix: dict[str, dict[str, int]], limit: int = 10) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for engine, per_opcode in op_mix.items():
        for opcode, count in per_opcode.items():
            rows.append({"engine": engine, "opcode": opcode, "count": count})
    rows.sort(key=lambda row: (-row["count"], row["engine"], row["opcode"]))
    return rows[:limit]


def _build_addr_labels(scratch_map: dict[int, tuple[str, int]] | None) -> dict[int, str]:
    if not scratch_map:
        return {}
    labels: dict[int, str] = {}
    for addr, entry in sorted(scratch_map.items()):
        if not isinstance(entry, tuple) or len(entry) != 2:
            continue
        name, length = entry
        if length <= 1:
            labels[addr] = str(name)
            continue
        for off in range(length):
            labels[addr + off] = f"{name}[{off}]"
    return labels


def _build_dependency_graph(
    ops: list[dict[str, Any]],
) -> dict[str, Any]:
    n_ops = len(ops)
    strict_preds = [set() for _ in range(n_ops)]
    weak_preds = [set() for _ in range(n_ops)]
    strict_succs = [set() for _ in range(n_ops)]
    weak_succs = [set() for _ in range(n_ops)]
    strict_edge_addrs: dict[tuple[int, int], set[int]] = {}
    weak_edge_addrs: dict[tuple[int, int], set[int]] = {}

    read_counts: Counter[int] = Counter()
    write_counts: Counter[int] = Counter()
    strict_addr_edges: Counter[int] = Counter()
    weak_addr_edges: Counter[int] = Counter()
    reader_ops: dict[int, set[int]] = defaultdict(set)
    writer_ops: dict[int, set[int]] = defaultdict(set)

    last_write: dict[int, int] = {}
    readers_since_write: dict[int, list[int]] = defaultdict(list)

    for op_idx, op in enumerate(ops):
        reads = [int(a) for a in op.get("reads", [])]
        writes = [int(a) for a in op.get("writes", [])]

        for addr in reads:
            read_counts[addr] += 1
            reader_ops[addr].add(op_idx)
            pred = last_write.get(addr, -1)
            if pred != -1:
                strict_preds[op_idx].add(pred)
                strict_succs[pred].add(op_idx)
                strict_edge_addrs.setdefault((pred, op_idx), set()).add(addr)
                strict_addr_edges[addr] += 1
            readers_since_write[addr].append(op_idx)

        for addr in writes:
            write_counts[addr] += 1
            writer_ops[addr].add(op_idx)
            pred = last_write.get(addr, -1)
            if pred != -1:
                strict_preds[op_idx].add(pred)
                strict_succs[pred].add(op_idx)
                strict_edge_addrs.setdefault((pred, op_idx), set()).add(addr)
                strict_addr_edges[addr] += 1
            for reader in readers_since_write.get(addr, []):
                if reader == op_idx:
                    continue
                weak_preds[op_idx].add(reader)
                weak_succs[reader].add(op_idx)
                weak_edge_addrs.setdefault((reader, op_idx), set()).add(addr)
                weak_addr_edges[addr] += 1
            last_write[addr] = op_idx
            readers_since_write[addr] = []

    return {
        "strict_preds": strict_preds,
        "weak_preds": weak_preds,
        "strict_succs": strict_succs,
        "weak_succs": weak_succs,
        "strict_edge_addrs": strict_edge_addrs,
        "weak_edge_addrs": weak_edge_addrs,
        "read_counts": read_counts,
        "write_counts": write_counts,
        "strict_addr_edges": strict_addr_edges,
        "weak_addr_edges": weak_addr_edges,
        "reader_ops": reader_ops,
        "writer_ops": writer_ops,
    }


def _compute_earliest_cycles(
    strict_preds: list[set[int]],
    weak_preds: list[set[int]],
) -> tuple[list[int], list[tuple[int, str] | None]]:
    n_ops = len(strict_preds)
    earliest = [0] * n_ops
    best_pred: list[tuple[int, str] | None] = [None] * n_ops

    for op_idx in range(n_ops):
        best_cycle = 0
        best_meta: tuple[int, str] | None = None

        for pred in sorted(strict_preds[op_idx]):
            cand = earliest[pred] + 1
            if cand > best_cycle:
                best_cycle = cand
                best_meta = (pred, "strict")

        for pred in sorted(weak_preds[op_idx]):
            cand = earliest[pred]
            if cand > best_cycle:
                best_cycle = cand
                best_meta = (pred, "weak")

        earliest[op_idx] = best_cycle
        best_pred[op_idx] = best_meta

    return earliest, best_pred


def _critical_chain(
    ops: list[dict[str, Any]],
    earliest: list[int],
    best_pred: list[tuple[int, str] | None],
    strict_edge_addrs: dict[tuple[int, int], set[int]],
    weak_edge_addrs: dict[tuple[int, int], set[int]],
    addr_labels: dict[int, str],
) -> list[dict[str, Any]]:
    if not ops:
        return []

    end_idx = max(
        range(len(ops)),
        key=lambda idx: (
            earliest[idx],
            int(ops[idx].get("crit_path", 0)),
            int(ops[idx].get("scheduled_cycle", -1)),
        ),
    )

    chain: list[dict[str, Any]] = []
    cur = end_idx
    while cur is not None:
        op = ops[cur]
        incoming = best_pred[cur]
        dep_type = None
        dep_addrs: list[int] = []
        if incoming is not None:
            dep_type = incoming[1]
            pred = incoming[0]
            if dep_type == "strict":
                dep_addrs = sorted(strict_edge_addrs.get((pred, cur), set()))
            else:
                dep_addrs = sorted(weak_edge_addrs.get((pred, cur), set()))

        chain.append(
            {
                "op_id": int(op.get("op_id", cur)),
                "engine": op.get("engine"),
                "scheduled_cycle": int(op.get("scheduled_cycle", -1)),
                "earliest_cycle": earliest[cur],
                "slack": int(op.get("scheduled_cycle", -1)) - earliest[cur],
                "crit_path": int(op.get("crit_path", 0)),
                "incoming_dep_type": dep_type,
                "incoming_dep_addrs": dep_addrs,
                "incoming_dep_labels": [addr_labels.get(a, f"scratch[{a}]") for a in dep_addrs[:4]],
            }
        )
        cur = incoming[0] if incoming is not None else None

    chain.reverse()
    return chain


def _engine_slot_totals(ops: list[dict[str, Any]]) -> dict[str, int]:
    totals = {engine: 0 for engine in ENGINES}
    for op in ops:
        engine = op.get("engine")
        if engine in totals:
            totals[engine] += int(op.get("slot_count", 1))
    return totals


def _analyze_cycle_blockers(
    ops: list[dict[str, Any]],
    strict_preds: list[set[int]],
    weak_preds: list[set[int]],
    cycle_engine_counts: list[dict[str, int]],
) -> dict[str, Any]:
    n_ops = len(ops)
    scheduled_cycle = [int(op.get("scheduled_cycle", -1)) for op in ops]
    op_engine = [str(op.get("engine")) for op in ops]
    slot_count = [int(op.get("slot_count", 1)) for op in ops]

    max_strict_pred_cycle = [
        max((scheduled_cycle[p] for p in strict_preds[i]), default=-1) for i in range(n_ops)
    ]
    max_weak_pred_cycle = [
        max((scheduled_cycle[p] for p in weak_preds[i]), default=-1) for i in range(n_ops)
    ]
    first_ready_cycle = [
        max(max_strict_pred_cycle[i] + 1, max_weak_pred_cycle[i]) for i in range(n_ops)
    ]

    scheduled_by_cycle: dict[int, list[int]] = defaultdict(list)
    for i, cycle in enumerate(scheduled_cycle):
        if cycle >= 0:
            scheduled_by_cycle[cycle].append(i)

    blocker_counts: Counter[str] = Counter()
    blocker_by_engine: dict[str, Counter[str]] = {engine: Counter() for engine in ENGINES}
    idle_slots_by_reason: dict[str, Counter[str]] = {engine: Counter() for engine in ENGINES}
    cycle_hotspots: list[dict[str, Any]] = []

    remaining_ops = set(range(n_ops))
    for cycle in range(len(cycle_engine_counts)):
        used = {engine: int(cycle_engine_counts[cycle].get(engine, 0)) for engine in ENGINES}
        ready_ops_by_engine: dict[str, list[int]] = defaultdict(list)
        ready_fit_not_scheduled = 0

        for op_idx in list(remaining_ops):
            if first_ready_cycle[op_idx] > cycle:
                if max_strict_pred_cycle[op_idx] + 1 > cycle:
                    blocker_counts["strict_dep_wait"] += 1
                elif max_weak_pred_cycle[op_idx] > cycle:
                    blocker_counts["weak_dep_wait"] += 1
                else:
                    blocker_counts["dep_wait_unknown"] += 1
                continue

            engine = op_engine[op_idx]
            ready_ops_by_engine[engine].append(op_idx)

            if scheduled_cycle[op_idx] == cycle:
                continue

            free_slots = SLOT_LIMITS[engine] - used.get(engine, 0)
            if free_slots <= 0:
                blocker_counts["engine_full"] += 1
                blocker_by_engine[engine]["engine_full"] += 1
                continue
            if slot_count[op_idx] > free_slots:
                blocker_counts["slot_fragmentation"] += 1
                blocker_by_engine[engine]["slot_fragmentation"] += 1
                continue
            blocker_counts["scheduler_choice"] += 1
            blocker_by_engine[engine]["scheduler_choice"] += 1
            ready_fit_not_scheduled += 1

        idle_slots_this_cycle = 0
        for engine in ENGINES:
            free_slots = max(0, SLOT_LIMITS[engine] - used.get(engine, 0))
            if free_slots == 0:
                continue
            ready = ready_ops_by_engine.get(engine, [])
            reason = "no_ready_ops"
            if ready:
                fitting = [idx for idx in ready if slot_count[idx] <= free_slots]
                if not fitting:
                    reason = "slot_fragmentation"
                else:
                    unscheduled_fitting = [idx for idx in fitting if scheduled_cycle[idx] > cycle]
                    if unscheduled_fitting:
                        reason = "scheduler_choice"
                    else:
                        reason = "dependency_tail"
            idle_slots_by_reason[engine][reason] += free_slots
            idle_slots_this_cycle += free_slots

        if ready_fit_not_scheduled > 0:
            cycle_hotspots.append(
                {
                    "cycle": cycle,
                    "ready_fit_not_scheduled": ready_fit_not_scheduled,
                    "idle_slots": idle_slots_this_cycle,
                    "used": used,
                }
            )

        for op_idx in scheduled_by_cycle.get(cycle, []):
            remaining_ops.discard(op_idx)

    cycle_hotspots.sort(
        key=lambda row: (
            row["ready_fit_not_scheduled"],
            row["idle_slots"],
        ),
        reverse=True,
    )

    return {
        "blocker_counts": dict(blocker_counts),
        "blocker_by_engine": {
            engine: dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))
            for engine, counter in blocker_by_engine.items()
            if counter
        },
        "idle_slots_by_reason": {
            engine: dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))
            for engine, counter in idle_slots_by_reason.items()
        },
        "cycle_hotspots": cycle_hotspots[:12],
    }


def _derive_findings(report: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    blockers = Counter(report.get("global_blockers", {}))
    idle = report.get("global_idle_slots_by_reason", {})
    summary = report.get("summary", {})

    if blockers.get("scheduler_choice", 0) > 0:
        findings.append(
            "Scheduler leaves fittable ready ops unscheduled in multiple cycles. "
            "Try higher `scheduler_beam_width` and more `scheduler_multi_start_seeds`."
        )
    if blockers.get("strict_dep_wait", 0) > (blockers.get("engine_full", 0) + blockers.get("scheduler_choice", 0)):
        findings.append(
            "Strict dependencies dominate waiting pressure. Focus on breaking write-after-read chains by using "
            "more scratch temporaries for long-lived values."
        )
    load_idle = idle.get("load", {}).get("no_ready_ops", 0)
    valu_idle = idle.get("valu", {}).get("no_ready_ops", 0)
    if load_idle > 0 and valu_idle > 0:
        findings.append(
            "Both load and VALU spend idle slots with no ready work. The limiting factor is upstream dependency "
            "readiness, not raw engine width."
        )

    hotspots = report.get("scratch_hotspots", [])
    if hotspots:
        top = hotspots[0]
        findings.append(
            f"Hottest scratch location is `{top['label']}` (addr {top['addr']}) with "
            f"{top['tight_edges']} tight dependency edges."
        )

    if summary.get("total_headroom_cycles", 0) > 0:
        findings.append(
            f"Estimated schedule headroom is {summary['total_headroom_cycles']} cycles over conservative lower bounds."
        )

    return findings


def analyze_inefficiency_report(
    instrs: list[dict[str, list[tuple]]],
    schedule_profile: dict[str, Any] | None,
    scratch_map: dict[int, tuple[str, int]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(metadata or {})
    schedule_profile = schedule_profile or {}
    profile_segments = list(schedule_profile.get("segments", []))

    instr_segments, barriers = split_non_debug_segments(instrs, include_debug=False)
    addr_labels = _build_addr_labels(scratch_map)
    notes: list[str] = []
    if len(profile_segments) != len(instr_segments):
        notes.append(
            "Profile/instruction segment count mismatch. "
            f"profile={len(profile_segments)}, instructions={len(instr_segments)}"
        )

    segment_reports: list[dict[str, Any]] = []
    global_blockers: Counter[str] = Counter()
    global_idle_slots: dict[str, Counter[str]] = {engine: Counter() for engine in ENGINES}
    global_blockers_by_engine: dict[str, Counter[str]] = {engine: Counter() for engine in ENGINES}
    global_slack_hotspots: list[dict[str, Any]] = []

    global_reads: Counter[int] = Counter()
    global_writes: Counter[int] = Counter()
    global_strict_edges: Counter[int] = Counter()
    global_weak_edges: Counter[int] = Counter()
    global_strict_tight_edges: Counter[int] = Counter()
    global_weak_tight_edges: Counter[int] = Counter()
    global_strict_near_edges: Counter[int] = Counter()
    global_reader_ops: Counter[int] = Counter()
    global_writer_ops: Counter[int] = Counter()

    total_dep_lb = 0
    total_engine_lb = 0
    total_combined_lb = 0
    total_cycles = 0

    segment_count = max(len(profile_segments), len(instr_segments))
    for idx in range(segment_count):
        profile = profile_segments[idx] if idx < len(profile_segments) else {}
        instr_segment = instr_segments[idx] if idx < len(instr_segments) else []
        phase = str(profile.get("phase", f"segment:{idx}"))
        ops = list(profile.get("ops", []))

        if profile.get("cycle_engine_counts"):
            cycle_counts = [
                {engine: int(row.get(engine, 0)) for engine in ENGINES}
                for row in profile.get("cycle_engine_counts", [])
            ]
        else:
            cycle_counts = [
                {engine: len(bundle.get(engine, [])) for engine in ENGINES}
                for bundle in instr_segment
            ]

        dep = _build_dependency_graph(ops)
        earliest, best_pred = _compute_earliest_cycles(dep["strict_preds"], dep["weak_preds"])
        scheduled_cycles = [int(op.get("scheduled_cycle", -1)) for op in ops]
        slacks = [
            max(0, scheduled_cycles[i] - earliest[i])
            for i in range(len(ops))
            if scheduled_cycles[i] >= 0
        ]

        strict_tight_edges: Counter[int] = Counter()
        weak_tight_edges: Counter[int] = Counter()
        strict_near_edges: Counter[int] = Counter()
        for (pred, succ), addrs in dep["strict_edge_addrs"].items():
            pred_cycle = scheduled_cycles[pred]
            succ_cycle = scheduled_cycles[succ]
            if pred_cycle < 0 or succ_cycle < 0:
                continue
            gap = succ_cycle - pred_cycle - 1
            for addr in addrs:
                if gap == 0:
                    strict_tight_edges[addr] += 1
                if gap <= 2:
                    strict_near_edges[addr] += 1
        for (pred, succ), addrs in dep["weak_edge_addrs"].items():
            pred_cycle = scheduled_cycles[pred]
            succ_cycle = scheduled_cycles[succ]
            if pred_cycle < 0 or succ_cycle < 0:
                continue
            gap = succ_cycle - pred_cycle
            if gap == 0:
                for addr in addrs:
                    weak_tight_edges[addr] += 1

        dep_lb = (max(earliest) + 1) if earliest else 0
        engine_totals = _engine_slot_totals(ops)
        engine_lb = {
            engine: (
                (engine_totals[engine] + SLOT_LIMITS[engine] - 1) // SLOT_LIMITS[engine]
                if SLOT_LIMITS[engine] > 0
                else 0
            )
            for engine in ENGINES
        }
        max_engine_lb = max(engine_lb.values(), default=0)
        combined_lb = max(dep_lb, max_engine_lb)
        cycles = len(cycle_counts)
        headroom = max(0, cycles - combined_lb)

        blockers = _analyze_cycle_blockers(
            ops,
            dep["strict_preds"],
            dep["weak_preds"],
            cycle_counts,
        )
        op_mix = _opcode_mix(instr_segment)
        critical_chain = _critical_chain(
            ops,
            earliest,
            best_pred,
            dep["strict_edge_addrs"],
            dep["weak_edge_addrs"],
            addr_labels,
        )

        top_slack = []
        if slacks:
            hotspot_order = sorted(
                range(len(ops)),
                key=lambda i: (
                    max(0, scheduled_cycles[i] - earliest[i]),
                    int(ops[i].get("crit_path", 0)),
                    int(ops[i].get("priority", 0)),
                ),
                reverse=True,
            )
            for op_idx in hotspot_order[:10]:
                if scheduled_cycles[op_idx] < 0:
                    continue
                slack = max(0, scheduled_cycles[op_idx] - earliest[op_idx])
                if slack == 0:
                    continue
                item = {
                    "segment_index": idx,
                    "phase": phase,
                    "op_id": int(ops[op_idx].get("op_id", op_idx)),
                    "engine": ops[op_idx].get("engine"),
                    "scheduled_cycle": scheduled_cycles[op_idx],
                    "earliest_cycle": earliest[op_idx],
                    "slack": slack,
                    "crit_path": int(ops[op_idx].get("crit_path", 0)),
                    "priority": int(ops[op_idx].get("priority", 0)),
                }
                top_slack.append(item)
                global_slack_hotspots.append(item)

        candidate_runs = list(profile.get("scheduler_candidates", []))
        candidate_cycles = [int(c.get("cycles", 0)) for c in candidate_runs if "cycles" in c]
        candidate_spread = (max(candidate_cycles) - min(candidate_cycles)) if candidate_cycles else 0
        candidate_best_seed = None
        if candidate_runs:
            best = min(candidate_runs, key=lambda row: int(row.get("cycles", 10**9)))
            candidate_best_seed = best.get("seed")

        for key, count in dep["read_counts"].items():
            global_reads[key] += count
        for key, count in dep["write_counts"].items():
            global_writes[key] += count
        for key, count in dep["strict_addr_edges"].items():
            global_strict_edges[key] += count
        for key, count in dep["weak_addr_edges"].items():
            global_weak_edges[key] += count
        for key, count in strict_tight_edges.items():
            global_strict_tight_edges[key] += count
        for key, count in weak_tight_edges.items():
            global_weak_tight_edges[key] += count
        for key, count in strict_near_edges.items():
            global_strict_near_edges[key] += count
        for key, readers in dep["reader_ops"].items():
            global_reader_ops[key] += len(readers)
        for key, writers in dep["writer_ops"].items():
            global_writer_ops[key] += len(writers)

        global_blockers.update(blockers["blocker_counts"])
        for engine in ENGINES:
            global_idle_slots[engine].update(blockers["idle_slots_by_reason"].get(engine, {}))
            global_blockers_by_engine[engine].update(blockers["blocker_by_engine"].get(engine, {}))

        segment_reports.append(
            {
                "segment_index": idx,
                "phase": phase,
                "cycles": cycles,
                "op_count": len(ops),
                "engine_slot_totals": engine_totals,
                "engine_lower_bound_cycles": engine_lb,
                "dependency_lower_bound_cycles": dep_lb,
                "combined_lower_bound_cycles": combined_lb,
                "headroom_cycles": headroom,
                "slack": {
                    "avg": (sum(slacks) / len(slacks)) if slacks else 0.0,
                    "p50": _percentile(slacks, 50),
                    "p95": _percentile(slacks, 95),
                    "max": max(slacks) if slacks else 0,
                },
                "blockers": blockers["blocker_counts"],
                "blockers_by_engine": blockers["blocker_by_engine"],
                "idle_slots_by_reason": blockers["idle_slots_by_reason"],
                "hotspot_cycles": blockers["cycle_hotspots"],
                "top_slack_ops": top_slack,
                "critical_chain": critical_chain,
                "opcode_mix": op_mix,
                "top_opcodes": _flatten_top_opcodes(op_mix, limit=10),
                "scheduler_candidates": candidate_runs,
                "scheduler_candidate_spread": candidate_spread,
                "scheduler_best_seed": candidate_best_seed,
            }
        )

        total_dep_lb += dep_lb
        total_engine_lb += max_engine_lb
        total_combined_lb += combined_lb
        total_cycles += cycles

    scratch_hotspots = []
    all_addrs = set(global_reads) | set(global_writes) | set(global_strict_edges) | set(global_weak_edges)
    for addr in all_addrs:
        dep_edges = global_strict_edges.get(addr, 0) + global_weak_edges.get(addr, 0)
        scratch_hotspots.append(
            {
                "addr": addr,
                "label": addr_labels.get(addr, f"scratch[{addr}]"),
                "reads": global_reads.get(addr, 0),
                "writes": global_writes.get(addr, 0),
                "strict_edges": global_strict_edges.get(addr, 0),
                "weak_edges": global_weak_edges.get(addr, 0),
                "dep_edges": dep_edges,
                "tight_edges": (
                    global_strict_tight_edges.get(addr, 0) + global_weak_tight_edges.get(addr, 0)
                ),
                "near_strict_edges": global_strict_near_edges.get(addr, 0),
                "reader_ops": global_reader_ops.get(addr, 0),
                "writer_ops": global_writer_ops.get(addr, 0),
            }
        )
    scratch_hotspots.sort(
        key=lambda row: (
            row["tight_edges"],
            row["near_strict_edges"],
            row["dep_edges"],
            row["reads"] + row["writes"],
            row["writer_ops"],
            row["reader_ops"],
        ),
        reverse=True,
    )

    global_slack_hotspots.sort(
        key=lambda row: (row["slack"], row["crit_path"], row["priority"]),
        reverse=True,
    )

    report: dict[str, Any] = {
        "created_at_utc": metadata.get("created_at_utc"),
        "summary": {
            "segment_count": len(segment_reports),
            "barrier_cycles": len(barriers),
            "non_debug_cycles": total_cycles + len(barriers),
            "scheduled_segment_cycles": total_cycles,
            "dependency_lower_bound_cycles": total_dep_lb + len(barriers),
            "engine_lower_bound_cycles": total_engine_lb + len(barriers),
            "combined_lower_bound_cycles": total_combined_lb + len(barriers),
            "total_headroom_cycles": max(0, total_cycles - total_combined_lb),
        },
        "barriers": barriers,
        "segment_reports": segment_reports,
        "global_blockers": dict(sorted(global_blockers.items(), key=lambda kv: (-kv[1], kv[0]))),
        "global_blockers_by_engine": {
            engine: dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))
            for engine, counter in global_blockers_by_engine.items()
            if counter
        },
        "global_idle_slots_by_reason": {
            engine: dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))
            for engine, counter in global_idle_slots.items()
        },
        "global_top_slack_ops": global_slack_hotspots[:20],
        "scratch_hotspots": scratch_hotspots[:25],
        "metadata": metadata,
        "notes": notes,
    }
    report["findings"] = _derive_findings(report)
    return report


def _fmt_blocker_top(blockers: dict[str, int]) -> str:
    if not blockers:
        return "-"
    reason, count = max(blockers.items(), key=lambda kv: kv[1])
    return f"{reason} ({count})"


def render_inefficiency_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        f"# Inefficiency Report ({summary.get('non_debug_cycles', 0)} cycles)",
        "",
        "## Summary",
        f"- Segments: {summary.get('segment_count', 0)}",
        f"- Barrier cycles: {summary.get('barrier_cycles', 0)}",
        f"- Segment cycles: {summary.get('scheduled_segment_cycles', 0)}",
        f"- Combined lower-bound estimate: {summary.get('combined_lower_bound_cycles', 0)}",
        f"- Estimated headroom: {summary.get('total_headroom_cycles', 0)} cycles",
        "",
        "## Segment Headroom",
        "| idx | phase | cycles | lower_bound | headroom | avg_slack | p95_slack | top_blocker | seed_spread |",
        "|---:|:---|---:|---:|---:|---:|---:|:---|---:|",
    ]

    for segment in report.get("segment_reports", []):
        lines.append(
            "| {idx} | `{phase}` | {cycles} | {lb} | {headroom} | {avg:.2f} | {p95:.1f} | {blocker} | {spread} |".format(
                idx=segment["segment_index"],
                phase=segment["phase"],
                cycles=segment["cycles"],
                lb=segment["combined_lower_bound_cycles"],
                headroom=segment["headroom_cycles"],
                avg=segment["slack"]["avg"],
                p95=segment["slack"]["p95"],
                blocker=_fmt_blocker_top(segment.get("blockers", {})),
                spread=segment.get("scheduler_candidate_spread", 0),
            )
        )

    lines.extend(
        [
            "",
            "## Global Blockers",
            "| reason | count |",
            "|:---|---:|",
        ]
    )
    blockers = report.get("global_blockers", {})
    if blockers:
        for reason, count in blockers.items():
            lines.append(f"| `{reason}` | {count} |")
    else:
        lines.append("| (none) | 0 |")

    lines.extend(
        [
            "",
            "## Idle Slot Reasons",
            "| engine | no_ready_ops | slot_fragmentation | scheduler_choice | dependency_tail |",
            "|:---|---:|---:|---:|---:|",
        ]
    )
    idle = report.get("global_idle_slots_by_reason", {})
    for engine in ENGINES:
        row = idle.get(engine, {})
        lines.append(
            "| `{engine}` | {no_ready} | {frag} | {choice} | {tail} |".format(
                engine=engine,
                no_ready=row.get("no_ready_ops", 0),
                frag=row.get("slot_fragmentation", 0),
                choice=row.get("scheduler_choice", 0),
                tail=row.get("dependency_tail", 0),
            )
        )

    lines.extend(
        [
            "",
            "## Top Scratch Hotspots",
            "| addr | label | tight | near_strict | dep_edges | reads | writes |",
            "|---:|:---|---:|---:|---:|---:|---:|",
        ]
    )
    hotspots = report.get("scratch_hotspots", [])
    if hotspots:
        for row in hotspots[:15]:
            lines.append(
                "| {addr} | `{label}` | {tight} | {near} | {dep_edges} | {reads} | {writes} |".format(
                    addr=row["addr"],
                    label=row["label"],
                    tight=row["tight_edges"],
                    near=row["near_strict_edges"],
                    dep_edges=row["dep_edges"],
                    reads=row["reads"],
                    writes=row["writes"],
                )
            )
    else:
        lines.append("| 0 | (none) | 0 | 0 | 0 | 0 | 0 |")

    lines.extend(
        [
            "",
            "## Top Slack Ops",
            "| phase | op_id | engine | scheduled | earliest | slack | crit_path |",
            "|:---|---:|:---|---:|---:|---:|---:|",
        ]
    )
    slack_ops = report.get("global_top_slack_ops", [])
    if slack_ops:
        for row in slack_ops[:20]:
            lines.append(
                "| `{phase}` | {op_id} | `{engine}` | {scheduled} | {earliest} | {slack} | {crit} |".format(
                    phase=row["phase"],
                    op_id=row["op_id"],
                    engine=row["engine"],
                    scheduled=row["scheduled_cycle"],
                    earliest=row["earliest_cycle"],
                    slack=row["slack"],
                    crit=row["crit_path"],
                )
            )
    else:
        lines.append("| (none) | 0 | - | 0 | 0 | 0 | 0 |")

    best_chain_segment = None
    for seg in report.get("segment_reports", []):
        chain = seg.get("critical_chain", [])
        if not chain:
            continue
        if best_chain_segment is None:
            best_chain_segment = seg
            continue
        if seg["combined_lower_bound_cycles"] > best_chain_segment["combined_lower_bound_cycles"]:
            best_chain_segment = seg

    lines.append("")
    lines.append("## Longest Dependency Chain")
    if best_chain_segment and best_chain_segment.get("critical_chain"):
        lines.append(f"- Segment `{best_chain_segment['phase']}`")
        for row in best_chain_segment["critical_chain"][:20]:
            dep = row.get("incoming_dep_type")
            dep_str = "start"
            if dep:
                labels = row.get("incoming_dep_labels", [])
                dep_str = dep if not labels else f"{dep} via {', '.join(labels)}"
            lines.append(
                f"- op#{row['op_id']} `{row['engine']}` cycle={row['scheduled_cycle']} "
                f"earliest={row['earliest_cycle']} slack={row['slack']} ({dep_str})"
            )
    else:
        lines.append("- No critical chain data available.")

    lines.append("")
    lines.append("## Findings")
    findings = report.get("findings", [])
    if findings:
        for finding in findings:
            lines.append(f"- {finding}")
    else:
        lines.append("- No dominant inefficiency signal found.")

    notes = report.get("notes", [])
    if notes:
        lines.append("")
        lines.append("## Notes")
        for note in notes:
            lines.append(f"- {note}")

    lines.append("")
    return "\n".join(lines)


def write_inefficiency_artifacts(
    report: dict[str, Any],
    out_dir: str | Path,
    prefix: str = "latest_inefficiency",
) -> tuple[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{prefix}.json"
    md_path = out / f"{prefix}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(render_inefficiency_markdown(report), encoding="utf-8")
    return str(json_path), str(md_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Render markdown for an inefficiency JSON report.")
    parser.add_argument("--input-json", type=str, required=True)
    parser.add_argument("--output-md", type=str, default="")
    args = parser.parse_args()

    payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    md = render_inefficiency_markdown(payload)
    if args.output_md:
        Path(args.output_md).write_text(md, encoding="utf-8")
    else:
        print(md)
