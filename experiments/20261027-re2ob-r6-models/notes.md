# R6 notes

## Before the full run (2026-10-27)

- `config.yaml` and `training/run_r6.py` were written first. Then a smoke test ran the whole pipeline
  (all 5 models, `--combine`) on a reduced setting: ranking windows with rel < 160 s only and the first
  2 of the 4 grid settings per model. Its purpose was to check that every model fits and that combine works.
- **The smoke test printed scores and the decision of that reduced run** (by mistake; it should have printed
  only pass/fail). Those numbers were seen before this commit. They come from a different data subset and grid,
  so they are not R6 results, but this is recorded because they were seen before the pre-registration commit.
- After the smoke test only two things changed: a warning filter (`iprint` OptimizeWarning from
  scikit-learn 1.5.2 + scipy 1.18, no effect on results) and the detection `core` count (44) written into
  `config.yaml`. Models, grids, feature sets and decision rules were not changed.
- Environment: `.venv-r6` (`pip-freeze-r6.txt`) = the frozen R5 package set (numpy 2.5.4, scipy 1.18.1,
  scikit-learn 1.5.2, lightgbm 4.5.0) + xgboost 3.4.1 + catboost 1.2.10. The main `.venv` is left exactly as
  `experiments/20261027-re2ob-r5-freeze/pip-freeze-research.txt`.
