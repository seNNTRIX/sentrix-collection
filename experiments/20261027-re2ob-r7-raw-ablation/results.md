# R7 results (RE2-OB, raw-value ablation)

- Q1 (pre-registered primary): **SentriX processing helps RF (LOSO)**

## Ablation (Random Forest = SentriX base model)

| step | features | LOSO Avg@5 (95% CI) | LOSO AC@1 | rep Avg@5 (95% CI) |
|---|---|---|---|---|
| base model + raw values | raw18 | 0.844 (0.778–0.902) | 0.756 | 0.987 (0.969–1.000) |
| + baseline normalisation, identity features kept | core35 | 0.951 (0.918–0.978) | 0.878 | 0.998 (0.993–1.000) |
| + identity features removed = SentriX-model | rel18 | 0.958 (0.931–0.978) | 0.856 | 0.998 (0.993–1.000) |
| (alt) raw values added back | raw18+rel18 | 0.924 (0.880–0.962) | 0.844 | 0.998 (0.993–1.000) |

## Same ablation with LightGBM (secondary)

| step | features | LOSO Avg@5 (95% CI) | LOSO AC@1 | rep Avg@5 (95% CI) |
|---|---|---|---|---|
| base model + raw values | raw18 | 0.773 (0.700–0.838) | 0.600 | 0.980 (0.967–0.991) |
| + baseline normalisation, identity features kept | core35 | 0.893 (0.840–0.938) | 0.767 | 0.996 (0.987–1.000) |
| + identity features removed = SentriX-model | rel18 | 0.940 (0.902–0.969) | 0.833 | 0.998 (0.993–1.000) |
| (alt) raw values added back | raw18+rel18 | 0.900 (0.856–0.938) | 0.722 | 0.996 (0.987–1.000) |

## Paired differences (Avg@5, case bootstrap 95% CI)

| model | split | comparison | mean diff | 95% CI | verdict |
|---|---|---|---|---|---|
| rf | loso | rel18 - raw18 | 0.113 | 0.062–0.171 | better |
| rf | loso | rel18 - raw18+rel18 | 0.033 | 0.011–0.060 | better |
| rf | loso | core35 - raw18 | 0.107 | 0.053–0.162 | better |
| rf | rep | rel18 - raw18 | 0.011 | -0.002–0.031 | no difference |
| rf | rep | rel18 - raw18+rel18 | 0.000 | -0.007–0.007 | no difference |
| rf | rep | core35 - raw18 | 0.011 | 0.000–0.029 | no difference |
| lgbm | loso | rel18 - raw18 | 0.167 | 0.107–0.233 | better |
| lgbm | loso | rel18 - raw18+rel18 | 0.040 | 0.009–0.073 | better |
| lgbm | loso | core35 - raw18 | 0.120 | 0.062–0.182 | better |
| lgbm | rep | rel18 - raw18 | 0.018 | 0.007–0.031 | better |
| lgbm | rep | rel18 - raw18+rel18 | 0.002 | 0.000–0.007 | no difference |
| lgbm | rep | core35 - raw18 | 0.016 | 0.004–0.029 | better |

## Detection (LightGBM, repetition 3-fold)

| inputs | AUROC (95% CI) | AUPRC |
|---|---|---|
| raw18 aggregates | 0.822 (0.778–0.875) | 0.839 |
| rel18 aggregates | 0.984 (0.964–0.997) | 0.992 |

rel18 - raw18 AUROC: 0.162 (0.111–0.208) better

## LOSO Avg@5 by held-out root-cause service

| model / features | checkoutservice | currencyservice | emailservice | productcatalogservice | recommendationservice |
|---|---|---|---|---|---|
| rf|raw18 | 0.789 | 0.911 | 0.856 | 0.733 | 0.933 |
| rf|core35 | 0.967 | 0.944 | 1.000 | 0.844 | 1.000 |
| rf|rel18 | 0.944 | 0.978 | 1.000 | 0.911 | 0.956 |
| rf|raw18+rel18 | 0.922 | 0.978 | 1.000 | 0.767 | 0.956 |
| lgbm|raw18 | 0.744 | 0.778 | 0.856 | 0.611 | 0.878 |
| lgbm|core35 | 0.889 | 0.833 | 1.000 | 0.778 | 0.967 |
| lgbm|rel18 | 0.867 | 0.944 | 1.000 | 0.933 | 0.956 |
| lgbm|raw18+rel18 | 0.911 | 0.900 | 1.000 | 0.733 | 0.956 |
