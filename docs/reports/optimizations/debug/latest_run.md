# Kernel Diagnostics (1446 cycles)

## Engine Pressure
- `alu`: avg 0.05/12 (0.4%), saturated cycles 0, idle slots 17282
- `valu`: avg 5.55/6 (92.5%), saturated cycles 1210, idle slots 654
- `load`: avg 1.83/2 (91.7%), saturated cycles 1326, idle slots 239
- `store`: avg 0.02/2 (1.1%), saturated cycles 0, idle slots 2860
- `flow`: avg 0.35/1 (35.4%), saturated cycles 512, idle slots 934

## Bottlenecks
- valu utilization 92.5%
- load utilization 91.7%
- flow saturated for 35.4% cycles

## Critical Path Hotspots
- phase `kernel_body:0` op#2 engine `load` crit_path=519 cycle=0
- phase `kernel_body:0` op#3 engine `load` crit_path=518 cycle=1
- phase `kernel_body:0` op#57 engine `load` crit_path=518 cycle=0
- phase `kernel_body:0` op#89 engine `alu` crit_path=517 cycle=2
- phase `kernel_body:0` op#32 engine `load` crit_path=516 cycle=1
- phase `kernel_body:0` op#58 engine `load` crit_path=516 cycle=2
- phase `kernel_body:0` op#90 engine `load` crit_path=516 cycle=3
- phase `kernel_body:0` op#33 engine `valu` crit_path=515 cycle=2
- phase `kernel_body:0` op#91 engine `alu` crit_path=515 cycle=3
- phase `kernel_body:0` op#59 engine `load` crit_path=514 cycle=2
- phase `kernel_body:0` op#92 engine `load` crit_path=514 cycle=4
- phase `kernel_body:0` op#93 engine `alu` crit_path=513 cycle=4

## Phase Breakdown
- `kernel_body:0`: 1446 cycles (alu 0.4%, valu 92.5%, load 91.7%, store 1.1%, flow 35.4%)

## Candidate Actions
- `cand_valu_001` Reduce VALU pressure in depth-specific path: VALU is near saturation, so replacing arithmetic with flow where safe or reducing per-depth operations should lower cycle count. (confidence 0.78, impact: valu)
- `cand_load_001` Lower gather cost for deeper rounds: Load engine pressure indicates gather rounds still dominate; reducing gather frequency or clustering gather-heavy groups can free cycles. (confidence 0.66, impact: load)
- `cand_flow_001` Tune flow/VALU tradeoff: Flow usage is material and can bottleneck at one slot per cycle; test arithmetic alternatives when they do not increase VALU critical path too much. (confidence 0.62, impact: flow, valu)
- `cand_sched_001` Retune scheduler priority bias: Different critical-path and engine bias weights can improve slot fill without changing kernel semantics. (confidence 0.71, impact: valu, load, flow)
- `cand_guardrails_001` Preserve known safety guardrails: Apply new experiments with explicit dependency anchoring and avoid previously regressive root-cache and weakly anchored vselect rewrites. (confidence 0.95, impact: correctness)
