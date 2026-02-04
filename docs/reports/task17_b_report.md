# Task 17B Report: Revert Task 17 Regression

Date: 2026-02-04

## Goal
Document the rollback of Task 17 (cache top tree levels in scratch) after it introduced a performance regression versus Task 16.

## Summary
Task 17 added a scratch cache for the root node and a conditional blend path. While correctness was preserved, the extra compare/blend ops increased cycle count. We reverted those changes to restore Task 16 performance.

## Evidence
- Task 16 cycles: **2177**
- Task 17 cycles: **2351** (regression)
- After rollback: **2177**

## What Was Reverted
- Removed scratch cache for the root node (`tree_cache0`) and vector broadcast (`vec_tree_cache0`).
- Removed conditional blend ops in both vector and scalar paths.
- Dropped per-group `vec_cache_tmp` scratch registers used by the blend logic.

## Tests Run
Command:
```
python tests/submission_tests.py
```

Result:
- Correctness tests passed.
- Speed tests still fail thresholds (as in Task 16), but cycles are back to **2177**.

## Files Touched
- `perf_takehome.py`
- `docs/improvements/IMPROVEMENTS_C.md`
- `docs/reports/task17_b_report.md`
