from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import json
import re
from typing import Any

from problem import SLOT_LIMITS


def _summarize_engine_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    per_cycle: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    engines = [engine for engine in SLOT_LIMITS if engine != "debug"]
    for row in rows:
        ts = int(row["ts"])
        engine = row["engine"]
        if engine not in engines:
            continue
        per_cycle[ts][engine] += 1

    cycle_ids = sorted(per_cycle)
    stats = {}
    for engine in engines:
        values = [per_cycle[cycle].get(engine, 0) for cycle in cycle_ids]
        limit = SLOT_LIMITS[engine]
        total = sum(values)
        n = len(values)
        avg = total / n if n else 0.0
        stats[engine] = {
            "avg": avg,
            "util_pct": (avg / limit * 100) if n else 0.0,
            "max": max(values) if values else 0,
            "limit": limit,
            "cycles": n,
        }

    return {
        "cycles": len(cycle_ids),
        "engine_pressure": stats,
    }


def _analyze_with_perfetto(trace_path: Path) -> dict[str, Any]:
    try:
        from perfetto.trace_processor import TraceProcessor
    except Exception as exc:  # pragma: no cover - dependency optional
        raise RuntimeError("perfetto package not installed") from exc

    tp = TraceProcessor(trace=str(trace_path))
    query = """
    SELECT s.ts AS ts, t.name AS thread_name
    FROM slice s
    JOIN thread_track tt ON s.track_id = tt.id
    JOIN thread t ON tt.utid = t.utid
    """
    rows = tp.query(query)
    parsed = []
    for row in rows:
        thread_name = str(row.thread_name)
        engine = thread_name.split("-", 1)[0]
        parsed.append({"ts": int(row.ts), "engine": engine})

    summary = _summarize_engine_counts(parsed)
    summary["backend"] = "perfetto"
    return summary


def _analyze_with_json(trace_path: Path) -> dict[str, Any]:
    raw = trace_path.read_text(encoding="utf-8")
    # The simulator writes a trailing comma after each event, including the last
    # one before the closing bracket. Normalize to valid JSON for parsing.
    raw = re.sub(r",\s*\]", "]", raw)
    data = json.loads(raw)
    tid_name = {}
    rows = []

    for event in data:
        if event.get("ph") == "M" and event.get("name") == "thread_name":
            tid_name[(event.get("pid"), event.get("tid"))] = event.get("args", {}).get("name", "")

    for event in data:
        if event.get("ph") != "X":
            continue
        tid = event.get("tid")
        pid = event.get("pid")
        thread_name = tid_name.get((pid, tid), "")
        engine = thread_name.split("-", 1)[0]
        rows.append({"ts": int(event.get("ts", 0)), "engine": engine})

    summary = _summarize_engine_counts(rows)
    summary["backend"] = "json"
    return summary


def analyze_trace(trace_path: str | Path = "trace.json") -> dict[str, Any]:
    trace_file = Path(trace_path)
    if not trace_file.exists():
        raise FileNotFoundError(f"Trace file not found: {trace_file}")

    try:
        return _analyze_with_perfetto(trace_file)
    except Exception:
        return _analyze_with_json(trace_file)


if __name__ == "__main__":
    report = analyze_trace()
    print(json.dumps(report, indent=2, sort_keys=True))
