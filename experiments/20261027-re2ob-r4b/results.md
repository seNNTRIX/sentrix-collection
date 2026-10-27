# R4b results (RE2-OB, unseen root-cause service)

features: core 35, rel 18; monotone +1 on 12 rel features

## Fingerprint probe (predict the candidate's service from its features; diagnostic only)

| features | candidates | accuracy | chance |
|---|---|---|---|
| core | 11 candidates | 0.986 | 0.091 |
| core | 7 traced | 0.943 | 0.143 |
| rel | 11 candidates | 0.792 | 0.091 |
| rel | 7 traced | 0.926 | 0.143 |

## LOSO (primary; params by inner LOSO)

| method | AC@1 | AC@3 | Avg@5 (95% CI) | MRR | diff vs stat (95% CI) | verdict |
|---|---|---|---|---|---|---|
| stat_combined | 0.794 | 0.978 | 0.943 (0.916–0.967) | 0.886 | - | - |
| V2_rel | 0.844 | 0.967 | 0.942 (0.907–0.971) | 0.906 | -0.001 (-0.027 – 0.023) | no difference |
| V3_rel_mono | 0.856 | 0.978 | 0.951 (0.920–0.978) | 0.914 | 0.008 (-0.018 – 0.036) | no difference |
| V1_core | 0.767 | 0.911 | 0.889 (0.833–0.933) | 0.846 | -0.054 (-0.100 – -0.012) | worse |
| V4_hybrid | 0.865 | 0.989 | 0.959 (0.933–0.979) | 0.923 | 0.016 (0.001 – 0.030) | better |

## Repetition 3-fold CV (secondary)

| method | AC@1 | AC@3 | Avg@5 (95% CI) | MRR | diff vs stat (95% CI) | verdict |
|---|---|---|---|---|---|---|
| stat_combined | 0.794 | 0.978 | 0.943 (0.916–0.967) | 0.886 | - | - |
| V2_rel | 0.978 | 1.000 | 0.996 (0.989–1.000) | 0.989 | 0.052 (0.031 – 0.078) | better |
| V3_rel_mono | 0.978 | 1.000 | 0.996 (0.989–1.000) | 0.989 | 0.052 (0.030 – 0.078) | better |
| V1_core | 0.989 | 1.000 | 0.996 (0.987–1.000) | 0.993 | 0.052 (0.032 – 0.077) | better |
| V4_hybrid | 0.911 | 1.000 | 0.981 (0.970–0.991) | 0.955 | 0.038 (0.022 – 0.058) | better |

## LOSO Avg@5 by held-out root-cause service

| held-out | stat_combined | V2_rel | V3_rel_mono | V1_core | V4_hybrid |
|---|---|---|---|---|---|
| checkoutservice | 0.900 | 0.867 | 0.900 | 0.867 | 0.906 |
| currencyservice | 0.928 | 0.944 | 0.933 | 0.833 | 0.972 |
| emailservice | 0.989 | 1.000 | 1.000 | 1.000 | 1.000 |
| productcatalogservice | 0.961 | 0.944 | 0.922 | 0.778 | 0.967 |
| recommendationservice | 0.939 | 0.956 | 1.000 | 0.967 | 0.950 |

## LOSO Avg@5 by fault

| method | cpu | delay | disk | loss | mem | socket |
|---|---|---|---|---|---|---|
| stat_combined | 0.973 | 0.860 | 0.993 | 0.853 | 1.000 | 0.980 |
| V2_rel | 1.000 | 0.907 | 1.000 | 0.747 | 1.000 | 1.000 |
| V3_rel_mono | 1.000 | 0.867 | 1.000 | 0.840 | 1.000 | 1.000 |
| V1_core | 0.987 | 0.773 | 0.973 | 0.613 | 1.000 | 0.987 |
| V4_hybrid | 1.000 | 0.920 | 1.000 | 0.833 | 1.000 | 1.000 |

## LOSO paired differences between variants

| comparison | mean diff | 95% CI | verdict |
|---|---|---|---|
| V2_rel - V3_rel_mono | -0.009 | -0.031 – 0.011 | no difference |
| V2_rel - V1_core | 0.053 | 0.022 – 0.089 | better |
| V2_rel - V4_hybrid | -0.017 | -0.036 – -0.001 | worse |
| V3_rel_mono - V1_core | 0.062 | 0.033 – 0.098 | better |
| V3_rel_mono - V4_hybrid | -0.008 | -0.032 – 0.013 | no difference |
| V1_core - V4_hybrid | -0.070 | -0.112 – -0.033 | worse |

## Chosen hyperparameters (LOSO, per held-out service)

- V1_core: checkoutservice: {'min_child_samples': 20, 'n_estimators': 300, 'num_leaves': 15}; currencyservice: {'min_child_samples': 100, 'n_estimators': 300, 'num_leaves': 7}; emailservice: {'min_child_samples': 100, 'n_estimators': 300, 'num_leaves': 15}; productcatalogservice: {'min_child_samples': 100, 'n_estimators': 100, 'num_leaves': 15}; recommendationservice: {'min_child_samples': 100, 'n_estimators': 300, 'num_leaves': 15}
- V2_rel: checkoutservice: {'min_child_samples': 100, 'n_estimators': 300, 'num_leaves': 15}; currencyservice: {'min_child_samples': 100, 'n_estimators': 100, 'num_leaves': 15}; emailservice: {'min_child_samples': 100, 'n_estimators': 300, 'num_leaves': 15}; productcatalogservice: {'min_child_samples': 20, 'n_estimators': 100, 'num_leaves': 15}; recommendationservice: {'min_child_samples': 100, 'n_estimators': 100, 'num_leaves': 15}
- V3_rel_mono: checkoutservice: {'min_child_samples': 100, 'n_estimators': 300, 'num_leaves': 7}; currencyservice: {'min_child_samples': 100, 'n_estimators': 300, 'num_leaves': 7}; emailservice: {'min_child_samples': 20, 'n_estimators': 300, 'num_leaves': 15}; productcatalogservice: {'min_child_samples': 20, 'n_estimators': 100, 'num_leaves': 15}; recommendationservice: {'min_child_samples': 100, 'n_estimators': 300, 'num_leaves': 7}

## Decision (pre-registered rule)

- tier: superior
- eligible: ['V4_hybrid']
- primary linux-v1 ranking method: **V4_hybrid**
