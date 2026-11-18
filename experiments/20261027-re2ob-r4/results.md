# R4 results (RE2-OB)

## Root-cause ranking (11 candidates, 90 cases, out-of-fold)

| method | features | AC@1 | AC@3 | Avg@5 (95% CI) | MRR | fold mean ± std | common faults | common faults+services |
|---|---|---|---|---|---|---|---|---|
| baseline stat_combined | - | 0.794 | 0.978 | 0.943 (0.916–0.967) | 0.886 | 0.943 ± 0.019 | 0.896 | 0.875 |
| lgbm metric | 26 | 0.933 | 0.967 | 0.967 (0.931–0.993) | 0.957 | 0.967 ± 0.019 | 0.933 | 0.917 |
| lgbm core | 35 | 0.989 | 1.000 | 0.996 (0.987–1.000) | 0.993 | 0.996 ± 0.006 | 0.991 | 0.989 |
| lgbm core+opt | 60 | 0.989 | 1.000 | 0.996 (0.987–1.000) | 0.993 | 0.996 ± 0.006 | 0.991 | 0.989 |
| lgbm core+log | 38 | 0.978 | 1.000 | 0.993 (0.982–1.000) | 0.987 | 0.993 ± 0.009 | 0.987 | 0.983 |
| lgbm core+nbr | 39 | 0.978 | 1.000 | 0.993 (0.982–1.000) | 0.987 | 0.993 ± 0.009 | 0.987 | 0.983 |
| lgbm all | 67 | 0.989 | 1.000 | 0.996 (0.987–1.000) | 0.993 | 0.996 ± 0.006 | 0.991 | 0.989 |
| lgbm core - f_ct_mask | - | 0.989 | 1.000 | 0.996 (0.987–1.000) | 0.993 | 0.996 ± 0.006 | 0.991 | 0.989 |
| lgbm core (traced candidates only) | - | 0.989 | 1.000 | 0.996 (0.987–1.000) | 0.993 | 0.996 ± 0.006 | 0.991 | 0.989 |
| baseline stat_combined (traced candidates only) | - | 0.806 | 0.989 | 0.950 (0.924–0.971) | 0.894 | 0.950 ± 0.017 | 0.909 | 0.892 |
| lgbm core (60 s windows) | - | 0.978 | 1.000 | 0.993 (0.982–1.000) | 0.987 | 0.993 ± 0.005 | 0.996 | 0.994 |
| joint classification (core) | - | 0.900 | 0.967 | 0.960 (0.931–0.984) | 0.936 | 0.960 ± 0.047 | 0.938 | 0.922 |

## Paired comparisons (Avg@5 difference, case bootstrap 95% CI)

| comparison | mean diff | 95% CI | verdict |
|---|---|---|---|
| metric - core | -0.029 | -0.060 – -0.004 | worse |
| core+opt - core | 0.000 | 0.000 – 0.000 | no difference |
| core+log - core | -0.002 | -0.007 – 0.000 | no difference |
| core+nbr - core | -0.002 | -0.007 – 0.000 | no difference |
| all - core | 0.000 | 0.000 – 0.000 | no difference |
| core - stat_combined | 0.052 | 0.032 – 0.077 | better |
| core-no-mask - core | 0.000 | 0.000 – 0.000 | no difference |
| core w60 - core w30 | -0.002 | -0.016 – 0.011 | no difference |

## Avg@5 by fault

| method | cpu | delay | disk | loss | mem | socket |
|---|---|---|---|---|---|---|
| baseline stat_combined | 0.973 | 0.860 | 0.993 | 0.853 | 1.000 | 0.980 |
| lgbm metric | 1.000 | 0.987 | 1.000 | 0.813 | 1.000 | 1.000 |
| lgbm core | 1.000 | 1.000 | 1.000 | 0.973 | 1.000 | 1.000 |
| lgbm core+opt | 1.000 | 1.000 | 1.000 | 0.973 | 1.000 | 1.000 |
| lgbm core+log | 1.000 | 1.000 | 1.000 | 0.960 | 1.000 | 1.000 |
| lgbm core+nbr | 1.000 | 1.000 | 1.000 | 0.960 | 1.000 | 1.000 |
| lgbm all | 1.000 | 1.000 | 1.000 | 0.973 | 1.000 | 1.000 |
| lgbm core - f_ct_mask | 1.000 | 1.000 | 1.000 | 0.973 | 1.000 | 1.000 |
| lgbm core (60 s windows) | 1.000 | 0.987 | 1.000 | 1.000 | 1.000 | 0.973 |
| joint classification (core) | 1.000 | 0.920 | 0.960 | 0.893 | 1.000 | 0.987 |

## Leave-one-service-out (params {'min_child_samples': 20, 'n_estimators': 100, 'num_leaves': 15})

| held-out root cause | n | lgbm AC@1 | lgbm Avg@5 | stat_combined Avg@5 |
|---|---|---|---|---|
| checkoutservice | 18 | 0.778 | 0.889 | 0.900 |
| currencyservice | 18 | 0.500 | 0.800 | 0.928 |
| emailservice | 18 | 1.000 | 1.000 | 0.989 |
| productcatalogservice | 18 | 0.667 | 0.767 | 0.961 |
| recommendationservice | 18 | 0.833 | 0.956 | 0.939 |

## Joint classification fault type

accuracy 0.711, macro-F1 0.711

## Detection (window level, out-of-fold)

| model | features | AUROC (95% CI) | AUPRC |
|---|---|---|---|
| lgbm core | 44 | 0.984 (0.967–0.996) | 0.991 |
| lgbm all | 58 | 0.994 (0.982–1.000) | 0.997 |

## Feature importance (core, gain, top 15)

- f_cm_mem_limit_ratio_dmean: 122137
- f_ct_in_edge_p90_lr: 43966
- f_cm_net_tx_pkts_dmean: 35478
- f_cm_cpu_limit_ratio_dmax: 23676
- f_cm_mem_limit_ratio_dmax: 12719
- f_ct_mask: 8686
- f_cm_cpu_limit_ratio_mean: 7489
- f_cm_mem_limit_ratio_mean: 6772
- f_cm_net_rx_pkts_dmax: 5623
- f_ct_out_p90_lr: 5373
- f_ct_in_p50_lr: 4275
- f_cm_net_tx_pkts_dmax: 3588
- f_ct_in_p90_lr: 3441
- f_ct_in_rate_lr: 2519
- f_cm_cpu_cores_dmean: 2078

## Errors (core, AC@1 < 1): 1 cases

| case | fault | true | predicted top 3 |
|---|---|---|---|
| re2ob_checkoutservice_loss_1 | loss | checkoutservice | currencyservice, productcatalogservice, checkoutservice |
