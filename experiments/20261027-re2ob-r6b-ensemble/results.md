# R6b results (RE2-OB, rank-average ensembles of R6 models)

- R6 picks: ranking **rf|rel|pure**, detection **lgbm|all|pure**
- ranking decision: **rf|rel|pure** (replaces R6 pick: False; eligible [])
- detection decision: **lgbm|all|pure** (replaces R6 pick: False; eligible [])

## Root-cause ranking

| candidate | LOSO Avg@5 (95% CI) | vs R6 pick (95% CI) | verdict | LOSO AC@1 | rep Avg@5 | rep vs stat | predict ms/window |
|---|---|---|---|---|---|---|---|
| E_gbdt_stat|rel | 0.949 (0.914–0.976) | -0.009 (-0.027–0.006) | no difference | 0.850 | 0.997 | better | 0.150 |
| E_gbdt_stat|core | 0.924 (0.886–0.958) | -0.033 (-0.058–-0.013) | worse | 0.806 | 0.994 | better | 0.143 |
| E_gbdt_stat|all | 0.922 (0.880–0.957) | -0.036 (-0.061–-0.016) | worse | 0.822 | 0.996 | better | 0.154 |
| E_all|rel | 0.937 (0.899–0.968) | -0.021 (-0.044–-0.002) | worse | 0.828 | 0.992 | better | 0.274 |
| E_all|core | 0.911 (0.867–0.948) | -0.047 (-0.076–-0.023) | worse | 0.772 | 0.991 | better | 0.243 |
| E_all|all | 0.888 (0.841–0.929) | -0.070 (-0.102–-0.040) | worse | 0.706 | 0.996 | better | 0.288 |
| E_all_stat|rel | 0.941 (0.904–0.971) | -0.017 (-0.038–-0.000) | worse | 0.833 | 0.992 | better | 0.274 |
| E_all_stat|core | 0.931 (0.893–0.962) | -0.027 (-0.052–-0.004) | worse | 0.817 | 0.989 | better | 0.243 |
| E_all_stat|all | 0.918 (0.878–0.953) | -0.040 (-0.067–-0.018) | worse | 0.789 | 0.996 | better | 0.288 |
| *R6 pick (rf|rel|pure)* | 0.958 (0.931–0.978) | - | - | 0.856 | 0.998 | - | - |
| *stat_combined* | 0.943 (0.916–0.967) | - | - | 0.794 | 0.943 | - | - |
| *R5 V4 (R4b run, different grid)* | 0.959 (0.933–0.979) | - | - | 0.865 | 0.981 | - | - |

## Members: LOSO Avg@5

| member | Avg@5 |
|---|---|
| logreg|rel | 0.880 |
| logreg|core | 0.876 |
| logreg|all | 0.731 |
| rf|rel | 0.958 |
| rf|core | 0.951 |
| rf|all | 0.918 |
| lgbm|rel | 0.940 |
| lgbm|core | 0.893 |
| lgbm|all | 0.922 |
| xgb|rel | 0.940 |
| xgb|core | 0.893 |
| xgb|all | 0.902 |
| catboost|rel | 0.933 |
| catboost|core | 0.902 |
| catboost|all | 0.902 |
| stat_combined | 0.943 |

## Member diversity: mean per-case Spearman correlation of candidate scores (LOSO)

- rel: logreg~rf 0.44; logreg~lgbm 0.44; logreg~xgb 0.45; logreg~catboost 0.45; logreg~stat 0.29; rf~lgbm 0.77; rf~xgb 0.76; rf~catboost 0.76; rf~stat 0.69; lgbm~xgb 0.94; lgbm~catboost 0.92; lgbm~stat 0.67; xgb~catboost 0.91; xgb~stat 0.67; catboost~stat 0.71
- core: logreg~rf 0.65; logreg~lgbm 0.75; logreg~xgb 0.72; logreg~catboost 0.75; logreg~stat 0.43; rf~lgbm 0.85; rf~xgb 0.84; rf~catboost 0.84; rf~stat 0.65; lgbm~xgb 0.95; lgbm~catboost 0.92; lgbm~stat 0.64; xgb~catboost 0.92; xgb~stat 0.65; catboost~stat 0.65
- all: logreg~rf 0.61; logreg~lgbm 0.72; logreg~xgb 0.73; logreg~catboost 0.61; logreg~stat 0.35; rf~lgbm 0.83; rf~xgb 0.83; rf~catboost 0.75; rf~stat 0.60; lgbm~xgb 0.90; lgbm~catboost 0.85; lgbm~stat 0.63; xgb~catboost 0.84; xgb~stat 0.59; catboost~stat 0.64

## Detection

| candidate | AUROC (95% CI) | AUPRC | vs R6 pick (95% CI) | verdict | predict ms/window |
|---|---|---|---|---|---|
| D_all|rel | 0.994 (0.985–0.999) | 0.996 | -0.002 (-0.005–-0.000) | worse | 0.022 |
| D_all|core | 0.990 (0.974–0.999) | 0.995 | -0.006 (-0.014–-0.001) | worse | 0.023 |
| D_all|all | 0.996 (0.989–1.000) | 0.997 | -0.000 (-0.002–0.001) | no difference | 0.024 |
| D_all_stat|rel | 0.995 (0.988–0.999) | 0.997 | -0.001 (-0.003–0.001) | no difference | 0.022 |
| D_all_stat|core | 0.993 (0.981–0.999) | 0.996 | -0.003 (-0.008–-0.000) | worse | 0.023 |
| D_all_stat|all | 0.997 (0.991–1.000) | 0.998 | 0.001 (-0.001–0.004) | no difference | 0.024 |
| *R6 pick (lgbm|all|pure)* | 0.996 (0.988–1.000) | 0.998 | - | - | - |

## Not tried

- stacking / learned weights: 90 cases are too few without nested CV (config.yaml not_decided_here)
