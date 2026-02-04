# Task One Report: VLIW Scheduler / Slot Packer

## Plan
- Add a slot-level dependency analyzer to compute scratch reads/writes per instruction slot.
- Implement a VLIW packer that groups slots into bundles while respecting engine slot limits and RAW/WAW hazards, allowing WAR within the same cycle.
- Enable the packer in `KernelBuilder.build_kernel` for the loop body.
- Run submission tests to validate correctness and observe cycle count.

## Implementation Summary
- Added `_slot_reads_writes` to `KernelBuilder` to infer scratch read/write sets for `alu`, `valu`, `load`, `store`, `flow`, and `debug` slots.
- Updated `KernelBuilder.build` to support a VLIW packing mode that greedily fills a bundle in program order while preventing same-cycle RAW/WAW hazards and slot over-subscription.
- Enabled VLIW packing for the kernel body via `self.build(body, vliw=True)`.

## Tests Run
- `python tests/submission_tests.py`

## Results
- Correctness test passed.
- Speedup test (`cycles < baseline`) passed.
- Higher speed threshold tests failed as expected with only Task One implemented.

Observed cycle count:
- `110871` cycles (speedup over baseline: `~1.33x`).

## Notes
- The VLIW packer improves utilization without changing algorithmic structure, but does not approach the sub-20k cycle thresholds in `submission_tests.py`. Additional improvements from `IMPROVEMENTS_C` would be required to pass those tests, but were out of scope per “Task One only.”
