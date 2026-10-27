# R6 results (RE2-OB, model family x feature set)

- ranking pick: **rf|rel|pure** (best LOSO: rf|rel|hybrid; 7 eligible)
- detection pick: **lgbm|all|pure** (best AUROC: catboost|all|pure; 3 eligible)

## Root-cause ranking

| candidate | LOSO Avg@5 (95% CI) | vs best (95% CI) | LOSO AC@1 | rep Avg@5 | rep vs stat | eligible |
|---|---|---|---|---|---|---|
| rf|rel|hybrid | 0.963 (0.942–0.980) | best | 0.856 | 0.986 | better | yes |
| rf|core|hybrid | 0.961 (0.941–0.979) | -0.002 (-0.016–0.010) | 0.844 | 0.986 | better | yes |
| lgbm|rel|hybrid | 0.960 (0.933–0.980) | -0.003 (-0.012–0.004) | 0.867 | 0.981 | better | yes |
| rf|rel|pure | 0.958 (0.931–0.978) | -0.006 (-0.020–0.008) | 0.856 | 0.998 | better | yes |
| xgb|rel|hybrid | 0.954 (0.922–0.978) | -0.009 (-0.023–0.003) | 0.852 | 0.979 | better | yes |
| rf|core|pure | 0.951 (0.918–0.978) | -0.012 (-0.041–0.013) | 0.878 | 0.998 | better | yes |
| rf|all|hybrid | 0.951 (0.922–0.973) | -0.012 (-0.032–0.002) | 0.837 | 0.986 | better | yes |
| lgbm|all|hybrid | 0.949 (0.921–0.971) | -0.014 (-0.029–-0.002) | 0.826 | 0.982 | better |  |
| catboost|rel|hybrid | 0.946 (0.912–0.971) | -0.018 (-0.032–-0.006) | 0.828 | 0.982 | better |  |
| stat_combined | 0.943 (0.916–0.967) | -0.020 (-0.037–-0.004) | 0.794 | 0.943 | - |  |
| lgbm|core|hybrid | 0.943 (0.911–0.969) | -0.020 (-0.041–-0.004) | 0.826 | 0.981 | better |  |
| lgbm|rel|pure | 0.940 (0.902–0.969) | -0.023 (-0.046–-0.004) | 0.833 | 0.998 | better |  |
| xgb|rel|pure | 0.940 (0.902–0.971) | -0.023 (-0.048–-0.002) | 0.833 | 0.991 | better |  |
| catboost|all|hybrid | 0.940 (0.906–0.967) | -0.023 (-0.043–-0.008) | 0.819 | 0.987 | better |  |
| xgb|all|hybrid | 0.939 (0.906–0.966) | -0.024 (-0.042–-0.010) | 0.806 | 0.981 | better |  |
| xgb|core|hybrid | 0.937 (0.903–0.964) | -0.027 (-0.047–-0.011) | 0.811 | 0.980 | better |  |
| catboost|core|hybrid | 0.936 (0.904–0.962) | -0.028 (-0.046–-0.013) | 0.793 | 0.981 | better |  |
| catboost|rel|pure | 0.933 (0.893–0.967) | -0.030 (-0.057–-0.007) | 0.822 | 1.000 | better |  |
| logreg|core|hybrid | 0.926 (0.882–0.961) | -0.038 (-0.071–-0.009) | 0.822 | 0.961 | no difference |  |
| lgbm|all|pure | 0.922 (0.878–0.958) | -0.041 (-0.073–-0.013) | 0.833 | 0.996 | better |  |
| rf|all|pure | 0.918 (0.869–0.958) | -0.046 (-0.084–-0.013) | 0.844 | 0.998 | better |  |
| logreg|rel|hybrid | 0.916 (0.867–0.958) | -0.047 (-0.086–-0.012) | 0.833 | 0.954 | no difference |  |
| xgb|all|pure | 0.902 (0.851–0.944) | -0.061 (-0.098–-0.030) | 0.811 | 0.996 | better |  |
| catboost|core|pure | 0.902 (0.851–0.944) | -0.061 (-0.099–-0.029) | 0.800 | 0.996 | better |  |
| catboost|all|pure | 0.902 (0.847–0.947) | -0.061 (-0.103–-0.026) | 0.822 | 0.998 | better |  |
| lgbm|core|pure | 0.893 (0.840–0.938) | -0.070 (-0.113–-0.034) | 0.767 | 0.996 | better |  |
| xgb|core|pure | 0.893 (0.838–0.938) | -0.070 (-0.111–-0.034) | 0.767 | 0.993 | better |  |
| logreg|rel|pure | 0.880 (0.816–0.936) | -0.083 (-0.138–-0.032) | 0.789 | 0.931 | no difference |  |
| logreg|core|pure | 0.876 (0.813–0.929) | -0.088 (-0.143–-0.038) | 0.789 | 0.951 | no difference |  |
| logreg|all|hybrid | 0.833 (0.773–0.888) | -0.130 (-0.189–-0.077) | 0.683 | 0.974 | better |  |
| logreg|all|pure | 0.731 (0.642–0.813) | -0.232 (-0.317–-0.151) | 0.667 | 0.960 | no difference |  |

## LOSO Avg@5 by held-out root-cause service (pure models)

| candidate | checkoutservice | currencyservice | emailservice | productcatalogservice | recommendationservice |
|---|---|---|---|---|---|
| stat_combined | 0.900 | 0.928 | 0.989 | 0.961 | 0.939 |
| logreg|rel|pure | 0.722 | 0.822 | 1.000 | 0.889 | 0.967 |
| logreg|core|pure | 0.700 | 0.878 | 0.944 | 0.889 | 0.967 |
| logreg|all|pure | 0.711 | 0.133 | 0.944 | 0.878 | 0.989 |
| rf|rel|pure | 0.944 | 0.978 | 1.000 | 0.911 | 0.956 |
| rf|core|pure | 0.967 | 0.944 | 1.000 | 0.844 | 1.000 |
| rf|all|pure | 0.911 | 0.956 | 1.000 | 0.756 | 0.967 |
| lgbm|rel|pure | 0.867 | 0.944 | 1.000 | 0.933 | 0.956 |
| lgbm|core|pure | 0.889 | 0.833 | 1.000 | 0.778 | 0.967 |
| lgbm|all|pure | 0.900 | 0.967 | 1.000 | 0.789 | 0.956 |
| xgb|rel|pure | 0.889 | 0.933 | 1.000 | 0.944 | 0.933 |
| xgb|core|pure | 0.878 | 0.844 | 1.000 | 0.833 | 0.911 |
| xgb|all|pure | 0.867 | 0.922 | 0.989 | 0.800 | 0.933 |
| catboost|rel|pure | 0.833 | 0.989 | 1.000 | 0.889 | 0.956 |
| catboost|core|pure | 0.811 | 0.933 | 1.000 | 0.811 | 0.956 |
| catboost|all|pure | 0.867 | 0.933 | 1.000 | 0.744 | 0.967 |

## LOSO Avg@5 by fault (pure models)

| candidate | cpu | delay | disk | loss | mem | socket |
|---|---|---|---|---|---|---|
| stat_combined | 0.973 | 0.860 | 0.993 | 0.853 | 1.000 | 0.980 |
| logreg|rel|pure | 0.987 | 0.827 | 0.933 | 0.600 | 0.933 | 1.000 |
| logreg|core|pure | 1.000 | 0.813 | 0.933 | 0.587 | 0.960 | 0.960 |
| logreg|all|pure | 0.800 | 0.613 | 0.800 | 0.507 | 0.880 | 0.787 |
| rf|rel|pure | 1.000 | 0.893 | 1.000 | 0.853 | 1.000 | 1.000 |
| rf|core|pure | 1.000 | 0.880 | 1.000 | 0.827 | 1.000 | 1.000 |
| rf|all|pure | 1.000 | 0.787 | 1.000 | 0.720 | 1.000 | 1.000 |
| lgbm|rel|pure | 1.000 | 0.880 | 1.000 | 0.760 | 1.000 | 1.000 |
| lgbm|core|pure | 0.987 | 0.773 | 0.973 | 0.640 | 1.000 | 0.987 |
| lgbm|all|pure | 1.000 | 0.800 | 1.000 | 0.733 | 1.000 | 1.000 |
| xgb|rel|pure | 1.000 | 0.920 | 0.987 | 0.733 | 1.000 | 1.000 |
| xgb|core|pure | 0.987 | 0.773 | 0.973 | 0.640 | 1.000 | 0.987 |
| xgb|all|pure | 1.000 | 0.800 | 1.000 | 0.613 | 1.000 | 1.000 |
| catboost|rel|pure | 1.000 | 0.813 | 1.000 | 0.800 | 0.987 | 1.000 |
| catboost|core|pure | 1.000 | 0.747 | 1.000 | 0.667 | 1.000 | 1.000 |
| catboost|all|pure | 1.000 | 0.760 | 1.000 | 0.653 | 1.000 | 1.000 |

## Detection (repetition 3-fold, out-of-fold windows)

| candidate | AUROC (95% CI) | AUPRC | vs best (95% CI) | eligible |
|---|---|---|---|---|
| catboost|all|pure | 0.997 (0.993–1.000) | 0.999 | best | yes |
| xgb|all|pure | 0.996 (0.990–1.000) | 0.998 | -0.001 (-0.003–0.000) | yes |
| lgbm|all|pure | 0.996 (0.988–1.000) | 0.998 | -0.002 (-0.005–0.000) | yes |
| rf|all|pure | 0.994 (0.985–0.999) | 0.997 | -0.003 (-0.009–-0.000) |  |
| catboost|rel|pure | 0.994 (0.984–0.999) | 0.996 | -0.004 (-0.009–-0.001) |  |
| catboost|core|pure | 0.992 (0.981–0.999) | 0.996 | -0.005 (-0.013–-0.001) |  |
| rf|rel|pure | 0.992 (0.980–0.999) | 0.996 | -0.006 (-0.014–-0.001) |  |
| rf|core|pure | 0.991 (0.978–0.998) | 0.995 | -0.007 (-0.015–-0.001) |  |
| xgb|rel|pure | 0.991 (0.979–0.998) | 0.994 | -0.007 (-0.014–-0.001) |  |
| xgb|core|pure | 0.989 (0.972–0.999) | 0.995 | -0.008 (-0.022–-0.001) |  |
| lgbm|rel|pure | 0.984 (0.964–0.997) | 0.992 | -0.013 (-0.029–-0.003) |  |
| lgbm|core|pure | 0.982 (0.963–0.994) | 0.989 | -0.015 (-0.031–-0.006) |  |
| logreg|rel|pure | 0.977 (0.959–0.993) | 0.989 | -0.020 (-0.037–-0.006) |  |
| logreg|core|pure | 0.963 (0.938–0.985) | 0.982 | -0.034 (-0.057–-0.013) |  |
| logreg|all|pure | 0.963 (0.936–0.985) | 0.982 | -0.035 (-0.060–-0.014) |  |
| stat_metric | 0.951 (0.928–0.969) | 0.969 | -0.047 (-0.068–-0.029) |  |

## Timing (final fits of the outer splits; this PC, 4 threads)

| model\|features | ranking LOSO fit s (median) | ranking predict ms/window | detection fit s | detection predict ms/window | total wall s |
|---|---|---|---|---|---|
| logreg|rel | 0.15 | 0.028 | 0.05 | 0.001 | 20 |
| logreg|core | 0.17 | 0.032 | 0.07 | 0.001 | 27 |
| logreg|all | 0.43 | 0.042 | 0.08 | 0.001 | 64 |
| rf|rel | 13.65 | 0.096 | 1.08 | 0.011 | 1648 |
| rf|core | 7.90 | 0.069 | 1.17 | 0.012 | 1276 |
| rf|all | 21.34 | 0.092 | 1.17 | 0.013 | 3124 |
| lgbm|rel | 0.69 | 0.064 | 0.55 | 0.004 | 107 |
| lgbm|core | 1.03 | 0.065 | 0.96 | 0.004 | 97 |
| lgbm|all | 1.97 | 0.078 | 0.87 | 0.005 | 187 |
| xgb|rel | 2.62 | 0.054 | 1.45 | 0.004 | 246 |
| xgb|core | 2.73 | 0.056 | 1.24 | 0.005 | 279 |
| xgb|all | 3.56 | 0.050 | 1.39 | 0.004 | 277 |
| catboost|rel | 11.97 | 0.033 | 0.39 | 0.001 | 744 |
| catboost|core | 7.90 | 0.022 | 0.83 | 0.001 | 590 |
| catboost|all | 8.69 | 0.025 | 1.39 | 0.001 | 729 |

## Chosen hyperparameters (LOSO per held-out service / detection per fold)

- logreg|rel ranking: checkoutservice: {'C': 0.01}; currencyservice: {'C': 10}; emailservice: {'C': 0.01}; productcatalogservice: {'C': 10}; recommendationservice: {'C': 0.1}
- logreg|rel detection: 1: {'C': 10}; 2: {'C': 10}; 3: {'C': 10}
- logreg|core ranking: checkoutservice: {'C': 0.01}; currencyservice: {'C': 0.01}; emailservice: {'C': 0.01}; productcatalogservice: {'C': 1}; recommendationservice: {'C': 0.01}
- logreg|core detection: 1: {'C': 10}; 2: {'C': 0.1}; 3: {'C': 10}
- logreg|all ranking: checkoutservice: {'C': 0.01}; currencyservice: {'C': 10}; emailservice: {'C': 0.01}; productcatalogservice: {'C': 10}; recommendationservice: {'C': 0.01}
- logreg|all detection: 1: {'C': 10}; 2: {'C': 1}; 3: {'C': 10}
- rf|rel ranking: checkoutservice: {'min_samples_leaf': 100, 'max_features': 'sqrt'}; currencyservice: {'min_samples_leaf': 100, 'max_features': 'sqrt'}; emailservice: {'min_samples_leaf': 100, 'max_features': 'sqrt'}; productcatalogservice: {'min_samples_leaf': 100, 'max_features': 'sqrt'}; recommendationservice: {'min_samples_leaf': 100, 'max_features': 'sqrt'}
- rf|rel detection: 1: {'min_samples_leaf': 20, 'max_features': 'sqrt'}; 2: {'min_samples_leaf': 20, 'max_features': 'sqrt'}; 3: {'min_samples_leaf': 20, 'max_features': 'sqrt'}
- rf|core ranking: checkoutservice: {'min_samples_leaf': 100, 'max_features': 'sqrt'}; currencyservice: {'min_samples_leaf': 100, 'max_features': 'sqrt'}; emailservice: {'min_samples_leaf': 100, 'max_features': 'sqrt'}; productcatalogservice: {'min_samples_leaf': 100, 'max_features': 'sqrt'}; recommendationservice: {'min_samples_leaf': 100, 'max_features': 'sqrt'}
- rf|core detection: 1: {'min_samples_leaf': 20, 'max_features': 'sqrt'}; 2: {'min_samples_leaf': 100, 'max_features': 0.5}; 3: {'min_samples_leaf': 20, 'max_features': 'sqrt'}
- rf|all ranking: checkoutservice: {'min_samples_leaf': 100, 'max_features': 0.5}; currencyservice: {'min_samples_leaf': 100, 'max_features': 'sqrt'}; emailservice: {'min_samples_leaf': 100, 'max_features': 'sqrt'}; productcatalogservice: {'min_samples_leaf': 100, 'max_features': 'sqrt'}; recommendationservice: {'min_samples_leaf': 100, 'max_features': 0.5}
- rf|all detection: 1: {'min_samples_leaf': 20, 'max_features': 'sqrt'}; 2: {'min_samples_leaf': 100, 'max_features': 'sqrt'}; 3: {'min_samples_leaf': 20, 'max_features': 0.5}
- lgbm|rel ranking: checkoutservice: {'num_leaves': 15, 'n_estimators': 300}; currencyservice: {'num_leaves': 15, 'n_estimators': 100}; emailservice: {'num_leaves': 15, 'n_estimators': 300}; productcatalogservice: {'num_leaves': 7, 'n_estimators': 100}; recommendationservice: {'num_leaves': 15, 'n_estimators': 100}
- lgbm|rel detection: 1: {'num_leaves': 31, 'n_estimators': 300}; 2: {'num_leaves': 15, 'n_estimators': 300}; 3: {'num_leaves': 15, 'n_estimators': 100}
- lgbm|core ranking: checkoutservice: {'num_leaves': 7, 'n_estimators': 300}; currencyservice: {'num_leaves': 7, 'n_estimators': 300}; emailservice: {'num_leaves': 15, 'n_estimators': 300}; productcatalogservice: {'num_leaves': 15, 'n_estimators': 100}; recommendationservice: {'num_leaves': 15, 'n_estimators': 300}
- lgbm|core detection: 1: {'num_leaves': 31, 'n_estimators': 300}; 2: {'num_leaves': 31, 'n_estimators': 300}; 3: {'num_leaves': 31, 'n_estimators': 100}
- lgbm|all ranking: checkoutservice: {'num_leaves': 7, 'n_estimators': 300}; currencyservice: {'num_leaves': 15, 'n_estimators': 300}; emailservice: {'num_leaves': 7, 'n_estimators': 300}; productcatalogservice: {'num_leaves': 7, 'n_estimators': 300}; recommendationservice: {'num_leaves': 15, 'n_estimators': 100}
- lgbm|all detection: 1: {'num_leaves': 15, 'n_estimators': 300}; 2: {'num_leaves': 15, 'n_estimators': 300}; 3: {'num_leaves': 15, 'n_estimators': 300}
- xgb|rel ranking: checkoutservice: {'max_depth': 4, 'n_estimators': 300}; currencyservice: {'max_depth': 3, 'n_estimators': 100}; emailservice: {'max_depth': 4, 'n_estimators': 300}; productcatalogservice: {'max_depth': 4, 'n_estimators': 100}; recommendationservice: {'max_depth': 4, 'n_estimators': 300}
- xgb|rel detection: 1: {'max_depth': 4, 'n_estimators': 100}; 2: {'max_depth': 6, 'n_estimators': 300}; 3: {'max_depth': 4, 'n_estimators': 100}
- xgb|core ranking: checkoutservice: {'max_depth': 4, 'n_estimators': 300}; currencyservice: {'max_depth': 4, 'n_estimators': 300}; emailservice: {'max_depth': 4, 'n_estimators': 300}; productcatalogservice: {'max_depth': 4, 'n_estimators': 300}; recommendationservice: {'max_depth': 3, 'n_estimators': 300}
- xgb|core detection: 1: {'max_depth': 4, 'n_estimators': 300}; 2: {'max_depth': 4, 'n_estimators': 300}; 3: {'max_depth': 4, 'n_estimators': 300}
- xgb|all ranking: checkoutservice: {'max_depth': 4, 'n_estimators': 300}; currencyservice: {'max_depth': 3, 'n_estimators': 100}; emailservice: {'max_depth': 4, 'n_estimators': 300}; productcatalogservice: {'max_depth': 4, 'n_estimators': 300}; recommendationservice: {'max_depth': 4, 'n_estimators': 300}
- xgb|all detection: 1: {'max_depth': 4, 'n_estimators': 300}; 2: {'max_depth': 4, 'n_estimators': 300}; 3: {'max_depth': 4, 'n_estimators': 300}
- catboost|rel ranking: checkoutservice: {'depth': 4, 'iterations': 300}; currencyservice: {'depth': 4, 'iterations': 100}; emailservice: {'depth': 4, 'iterations': 300}; productcatalogservice: {'depth': 4, 'iterations': 300}; recommendationservice: {'depth': 6, 'iterations': 300}
- catboost|rel detection: 1: {'depth': 4, 'iterations': 100}; 2: {'depth': 4, 'iterations': 100}; 3: {'depth': 6, 'iterations': 300}
- catboost|core ranking: checkoutservice: {'depth': 4, 'iterations': 300}; currencyservice: {'depth': 4, 'iterations': 300}; emailservice: {'depth': 4, 'iterations': 300}; productcatalogservice: {'depth': 6, 'iterations': 100}; recommendationservice: {'depth': 4, 'iterations': 100}
- catboost|core detection: 1: {'depth': 4, 'iterations': 100}; 2: {'depth': 6, 'iterations': 100}; 3: {'depth': 4, 'iterations': 300}
- catboost|all ranking: checkoutservice: {'depth': 4, 'iterations': 100}; currencyservice: {'depth': 4, 'iterations': 300}; emailservice: {'depth': 4, 'iterations': 300}; productcatalogservice: {'depth': 4, 'iterations': 100}; recommendationservice: {'depth': 4, 'iterations': 300}
- catboost|all detection: 1: {'depth': 6, 'iterations': 100}; 2: {'depth': 6, 'iterations': 300}; 3: {'depth': 4, 'iterations': 300}

## Decision (pre-registered rule, applied mechanically)

- ranking: best rf|rel|hybrid; eligible (simplest first) ['rf|rel|pure', 'rf|rel|hybrid', 'rf|core|pure', 'rf|core|hybrid', 'rf|all|hybrid', 'lgbm|rel|hybrid', 'xgb|rel|hybrid']; pick **rf|rel|pure**
- detection: best catboost|all|pure; eligible (simplest first) ['lgbm|all|pure', 'xgb|all|pure', 'catboost|all|pure']; pick **lgbm|all|pure**
