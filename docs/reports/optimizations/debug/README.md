# Optimization Debug Artifacts

This directory stores machine-readable outputs for agentic optimization workflows.

## Files

- `latest_run.json` / `latest_run.md`: most recent diagnostics run.
- `leaderboard.json` / `leaderboard.md`: results from auto-optimizer trial loops.
- `run_summary.json`: summary pointer file for the latest auto-loop run.
- `trials/trial_XXXX/`: per-trial diagnostics (and optional trace reports).

## Commands

Single diagnostic run (current/default strategy):

```bash
python -m tools.opt_debug.run_diagnostics
```

Standalone tooling self-check (outside `tests/`):

```bash
python -m tools.opt_debug.selfcheck
```

Auto optimizer loop (Optuna if installed; otherwise random search):

```bash
python -m tools.opt_debug.auto_optimize --trials 24 --backend auto
```

Auto optimizer loop with best-trial trace analysis:

```bash
python -m tools.opt_debug.auto_optimize --trials 24 --trace-best
```

## Optional dependencies

- `optuna` enables TPE-based search in `auto_optimize`.
- `perfetto` enables SQL-backed trace analysis backend in `analyze_trace`.

Without these dependencies, the tooling still runs with fallback behavior:

- random search instead of Optuna
- JSON trace parsing instead of Perfetto SQL
