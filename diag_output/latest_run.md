# Kernel Diagnostics (1382 cycles)

## Engine Pressure
- `alu`: avg 0.05/12 (0.4%), saturated cycles 0, idle slots 16514
- `valu`: avg 5.76/6 (96.1%), saturated cycles 1248, idle slots 325
- `load`: avg 1.90/2 (94.9%), saturated cycles 1307, idle slots 141
- `store`: avg 0.02/2 (1.2%), saturated cycles 0, idle slots 2732
- `flow`: avg 0.19/1 (18.5%), saturated cycles 256, idle slots 1126

## Bottlenecks
- valu utilization 96.1%
- load utilization 94.9%

## Critical Path Hotspots
- phase `kernel_body:0` op#2 engine `load` crit_path=523 cycle=1
- phase `kernel_body:0` op#3 engine `load` crit_path=522 cycle=2
- phase `kernel_body:0` op#4 engine `load` crit_path=522 cycle=0
- phase `kernel_body:0` op#68 engine `alu` crit_path=521 cycle=3
- phase `kernel_body:0` op#7 engine `load` crit_path=520 cycle=0
- phase `kernel_body:0` op#69 engine `load` crit_path=520 cycle=4
- phase `kernel_body:0` op#70 engine `alu` crit_path=519 cycle=4
- phase `kernel_body:0` op#71 engine `load` crit_path=518 cycle=5
- phase `kernel_body:0` op#72 engine `alu` crit_path=517 cycle=5
- phase `kernel_body:0` op#73 engine `load` crit_path=516 cycle=6
- phase `kernel_body:0` op#74 engine `alu` crit_path=515 cycle=6
- phase `kernel_body:0` op#75 engine `load` crit_path=514 cycle=7

## Phase Breakdown
- `kernel_body:0`: 1382 cycles (alu 0.4%, valu 96.1%, load 94.9%, store 1.2%, flow 18.5%)

## Candidate Actions
- `cand_valu_001` Reduce VALU pressure in depth-specific path: VALU is near saturation, so replacing arithmetic with flow where safe or reducing per-depth operations should lower cycle count. (confidence 0.78, impact: valu)
- `cand_load_001` Lower gather cost for deeper rounds: Load engine pressure indicates gather rounds still dominate; reducing gather frequency or clustering gather-heavy groups can free cycles. (confidence 0.66, impact: load)
- `cand_sched_001` Retune scheduler priority bias: Different critical-path and engine bias weights can improve slot fill without changing kernel semantics. (confidence 0.71, impact: valu, load, flow)
- `cand_guardrails_001` Preserve known safety guardrails: Apply new experiments with explicit dependency anchoring and avoid previously regressive root-cache and weakly anchored vselect rewrites. (confidence 0.95, impact: correctness)
