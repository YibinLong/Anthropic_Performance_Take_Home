# Inefficiency Report (1382 cycles)

## Summary
- Segments: 1
- Barrier cycles: 0
- Segment cycles: 1382
- Combined lower-bound estimate: 1328
- Estimated headroom: 54 cycles

## Segment Headroom
| idx | phase | cycles | lower_bound | headroom | avg_slack | p95_slack | top_blocker | seed_spread |
|---:|:---|---:|---:|---:|---:|---:|:---|---:|
| 0 | `kernel_body:0` | 1382 | 1328 | 54 | 533.20 | 1083.0 | strict_dep_wait (7475617) | 0 |

## Global Blockers
| reason | count |
|:---|---:|
| `strict_dep_wait` | 7475617 |
| `engine_full` | 129205 |
| `weak_dep_wait` | 1541 |

## Idle Slot Reasons
| engine | no_ready_ops | slot_fragmentation | scheduler_choice | dependency_tail |
|:---|---:|---:|---:|---:|
| `alu` | 15816 | 0 | 0 | 698 |
| `valu` | 42 | 0 | 0 | 283 |
| `load` | 132 | 0 | 0 | 9 |
| `store` | 2700 | 0 | 0 | 32 |
| `flow` | 1126 | 0 | 0 | 0 |

## Top Scratch Hotspots
| addr | label | tight | near_strict | dep_edges | reads | writes |
|---:|:---|---:|---:|---:|---:|---:|
| 828 | `tmp_addr_b` | 164 | 107 | 252 | 126 | 64 |
| 839 | `vec_addr_g0[2]` | 159 | 224 | 446 | 152 | 148 |
| 841 | `vec_addr_g0[4]` | 159 | 224 | 446 | 152 | 148 |
| 843 | `vec_addr_g0[6]` | 159 | 224 | 446 | 152 | 148 |
| 838 | `vec_addr_g0[1]` | 159 | 223 | 446 | 152 | 148 |
| 842 | `vec_addr_g0[5]` | 159 | 223 | 446 | 152 | 148 |
| 844 | `vec_addr_g0[7]` | 159 | 223 | 446 | 152 | 148 |
| 837 | `vec_addr_g0[0]` | 158 | 223 | 446 | 152 | 148 |
| 840 | `vec_addr_g0[3]` | 158 | 222 | 446 | 152 | 148 |
| 762 | `val_arr[192]` | 158 | 207 | 397 | 175 | 113 |
| 763 | `val_arr[193]` | 158 | 207 | 397 | 175 | 113 |
| 764 | `val_arr[194]` | 158 | 207 | 397 | 175 | 113 |
| 765 | `val_arr[195]` | 158 | 207 | 397 | 175 | 113 |
| 766 | `val_arr[196]` | 158 | 207 | 397 | 175 | 113 |
| 767 | `val_arr[197]` | 158 | 207 | 397 | 175 | 113 |

## Top Slack Ops
| phase | op_id | engine | scheduled | earliest | slack | crit_path |
|:---|---:|:---|---:|---:|---:|---:|
| `kernel_body:0` | 10711 | `load` | 1363 | 231 | 1132 | 26 |
| `kernel_body:0` | 10714 | `load` | 1363 | 231 | 1132 | 26 |
| `kernel_body:0` | 10717 | `valu` | 1364 | 232 | 1132 | 25 |
| `kernel_body:0` | 10718 | `valu` | 1365 | 233 | 1132 | 24 |
| `kernel_body:0` | 10719 | `valu` | 1366 | 234 | 1132 | 23 |
| `kernel_body:0` | 10720 | `valu` | 1366 | 234 | 1132 | 23 |
| `kernel_body:0` | 10721 | `valu` | 1367 | 235 | 1132 | 22 |
| `kernel_body:0` | 10722 | `valu` | 1368 | 236 | 1132 | 21 |
| `kernel_body:0` | 10723 | `valu` | 1369 | 237 | 1132 | 20 |
| `kernel_body:0` | 10724 | `valu` | 1369 | 237 | 1132 | 20 |

## Longest Dependency Chain
- Segment `kernel_body:0`
- op#2 `load` cycle=1 earliest=0 slack=1 (start)
- op#3 `load` cycle=2 earliest=1 slack=1 (strict via scratch[7])
- op#68 `alu` cycle=3 earliest=2 slack=1 (strict via inp_values_p)
- op#70 `alu` cycle=4 earliest=3 slack=1 (strict via tmp_addr_b)
- op#72 `alu` cycle=5 earliest=4 slack=1 (strict via tmp_addr_b)
- op#74 `alu` cycle=6 earliest=5 slack=1 (strict via tmp_addr_b)
- op#76 `alu` cycle=7 earliest=6 slack=1 (strict via tmp_addr_b)
- op#78 `alu` cycle=8 earliest=7 slack=1 (strict via tmp_addr_b)
- op#80 `alu` cycle=9 earliest=8 slack=1 (strict via tmp_addr_b)
- op#82 `alu` cycle=10 earliest=9 slack=1 (strict via tmp_addr_b)
- op#84 `alu` cycle=11 earliest=10 slack=1 (strict via tmp_addr_b)
- op#86 `alu` cycle=12 earliest=11 slack=1 (strict via tmp_addr_b)
- op#88 `alu` cycle=13 earliest=12 slack=1 (strict via tmp_addr_b)
- op#90 `alu` cycle=14 earliest=13 slack=1 (strict via tmp_addr_b)
- op#92 `alu` cycle=15 earliest=14 slack=1 (strict via tmp_addr_b)
- op#94 `alu` cycle=16 earliest=15 slack=1 (strict via tmp_addr_b)
- op#96 `alu` cycle=17 earliest=16 slack=1 (strict via tmp_addr_b)
- op#98 `alu` cycle=18 earliest=17 slack=1 (strict via tmp_addr_b)
- op#100 `alu` cycle=19 earliest=18 slack=1 (strict via tmp_addr_b)
- op#102 `alu` cycle=20 earliest=19 slack=1 (strict via tmp_addr_b)

## Findings
- Strict dependencies dominate waiting pressure. Focus on breaking write-after-read chains by using more scratch temporaries for long-lived values.
- Both load and VALU spend idle slots with no ready work. The limiting factor is upstream dependency readiness, not raw engine width.
- Hottest scratch location is `tmp_addr_b` (addr 828) with 164 tight dependency edges.
- Estimated schedule headroom is 54 cycles over conservative lower bounds.
