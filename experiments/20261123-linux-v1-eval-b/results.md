# linux-v1 evaluation

## Method A — RE2-OB frozen models applied unchanged (supplementary)

| ranking (eligible cpu/pod) | n | AC@1 | AC@3 | Avg@5 (95% CI) | MRR |
|---|---:|---:|---:|---|---:|
| rf | 22 | 0.500 | 0.909 | 0.827 (0.745–0.900) | 0.697 |
| v4 | 22 | 0.727 | 1.000 | 0.941 (0.900–0.977) | 0.860 |
| stat_combined | 22 | 0.500 | 0.818 | 0.782 (0.673–0.877) | 0.672 |
| random | 22 | 0.091 | 0.273 | 0.273 (0.273–0.273) | 0.275 |

| paired (Avg@5) | diff | 95% CI | verdict |
|---|---:|---|---|
| rf_minus_stat_combined | 0.045 | -0.036–0.127 | no difference |
| rf_minus_v4 | -0.114 | -0.186–-0.045 | worse |
| v4_minus_stat_combined | 0.159 | 0.091–0.232 | better |

| detection | AUROC (95% CI) | AUPRC | windows |
|---|---|---:|---:|
| lgbm_all58 | 0.873 (0.829–0.917) | 0.659 | 12473 |
| v1_rel36 | 0.774 (0.699–0.843) | 0.599 | 12473 |
| stat_metric | 0.715 (0.638–0.789) | 0.369 | 12473 |

| edge ranking (eligible delay/loss) | n | AC@1 | AC@3 | Avg@5 |
|---|---:|---:|---:|---:|
| stat edge | 26 | 0.615 | 0.692 | 0.700 |
| random | 26 | 0.125 | 0.375 | 0.375 |

Node view of edge faults (AC@1 / AC@3): either 0.385 / 0.885, source 0.077 / 0.462, destination 0.308 / 0.692

- Method A: RE2-OB final models applied unchanged; paymentservice is an unseen root cause.
- rx/tx packet features are NaN in linux-v1 -> 0 in RF (LINUX-V1-DATA-TRANSLATION.md 1).
- Run alarm rates need the RE2-OB training normal-window threshold (Method B / --re2ob).

## Method B — repetition 3-fold (main)

| ranking (eligible cpu/pod) | n | AC@1 | AC@3 | Avg@5 (95% CI) | MRR |
|---|---:|---:|---:|---|---:|
| rf18 | 22 | 0.955 | 1.000 | 0.991 (0.973–1.000) | 0.977 |
| rf14 | 22 | 0.909 | 1.000 | 0.982 (0.955–1.000) | 0.955 |
| stat_combined | 22 | 0.500 | 0.818 | 0.782 (0.673–0.877) | 0.672 |
| random | 22 | 0.091 | 0.273 | 0.273 (0.273–0.273) | 0.275 |

| paired (Avg@5) | diff | 95% CI | verdict |
|---|---:|---|---|
| rf18_minus_stat_combined | 0.209 | 0.114–0.318 | better |
| rf14_minus_rf18 | -0.009 | -0.027–0.000 | no difference |

| detection | AUROC (95% CI) | AUPRC | windows |
|---|---|---:|---:|
| lgbm_all58 | 0.965 (0.930–0.990) | 0.897 | 12473 |

Run alarms: fault 0.944 of 54, control false alarm 0.377 of 69, median alarm at onset+100.000 s

Node view of edge faults (AC@1 / AC@3): either 0.346 / 0.808, source 0.077 / 0.615, destination 0.269 / 0.731

- Method B: frozen hyperparameters, no selection; training = RE2-OB 90 + linux-v1 other folds.
- rf14 = rel18 without the 4 rx/tx features (secondary, pre-registered sensitivity).
