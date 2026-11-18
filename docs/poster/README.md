# 포스터 표·그래프 만들기

모든 명령은 저장소 루트(`sentrix-final-v1`)에서 Git Bash로 실행한다. 가상환경은 `.venv-r6`(XGBoost·CatBoost 포함)를 쓴다.

```bash
export PYTHONIOENCODING=utf-8 PYTHONWARNINGS=ignore
PY=.venv-r6/Scripts/python.exe
```

## 1. 표·그래프만 만들기 (1분)

commit된 실험 결과를 읽어서 그린다. 학습은 하지 않는다.

```bash
$PY scripts/make_poster_figures.py --out docs/poster/re2ob
```

| 파일 | 내용 |
|---|---|
| `table_main.png`, `table_main.csv` | 원인 분석 성능 비교 표 (random, BARO, 통계 방법, SentriX-model) |
| `fig_ablation.png` | 기본 모델 + SentriX 처리의 효과 (원래 값 → 정규화 → SentriX-model) |
| `fig_models.png` | 모델 5종 × 입력 3종 비교 |
| `fig_faults.png` | 장애 종류별 원인 순위 정확도 |
| `fig_detection_roc.png` | 장애 탐지 ROC 곡선 (`data/features/re2ob-v0` 필요) |
| `values.json` | 그림에 쓴 숫자 전부 |

## 2. 실험부터 직접 다시 돌리기 (1~2시간)

결과를 새 폴더(`experiments/rerun-*`)에 만들어서, commit된 결과와 섞이지 않게 한다. 같은 코드·seed라 숫자는 commit된 결과와 같아야 한다.

**R6: 모델 5종 × 입력 3종** (모델 5개를 동시에 실행, 가장 오래 걸리는 Random Forest 약 1시간)

```bash
O6=experiments/rerun-r6
for m in logreg rf lgbm xgb catboost; do $PY -m training.run_r6 --out $O6 --model $m > $O6-$m.log 2>&1 & done; wait
$PY -m training.run_r6 --out $O6 --combine
```

**R7: 원래 값 ablation** (R6 결과 폴더를 읽는다)

```bash
O7=experiments/rerun-r7
$PY -m features.build_raw_r7 --out data/features/re2ob-r7-raw-rerun
$PY -m training.run_r7 --raw data/features/re2ob-r7-raw-rerun --r6 $O6 --out $O7 --check
for spec in "rf raw18" "rf raw18+rel18" "lgbm raw18" "lgbm raw18+rel18"; do set -- $spec; $PY -m training.run_r7 --raw data/features/re2ob-r7-raw-rerun --r6 $O6 --out $O7 --model $1 --fset $2 & done
$PY -m training.run_r7 --raw data/features/re2ob-r7-raw-rerun --r6 $O6 --out $O7 --detection & wait
$PY -m training.run_r7 --raw data/features/re2ob-r7-raw-rerun --r6 $O6 --out $O7 --combine
```

**다시 돌린 결과로 그리기**

```bash
$PY scripts/make_poster_figures.py --r6 $O6 --r7 $O7 --out docs/poster/re2ob-rerun
```

- random과 BARO 숫자는 `experiments/20261027-re2ob-baselines/`(R3)의 commit된 결과를 그대로 쓴다. BARO는 RCAEval 패키지가 든 별도 가상환경이 필요하다(`evaluation/run_rcaeval_baro.py` 참고).

## 3. 표기 규칙

- 모든 숫자는 **RE2-OB 90 case** 결과다. 그림 제목에 데이터 이름이 들어가 있으니 지우지 않는다.
- "처음 보는 서비스" = LOSO(원인 서비스 하나를 빼고 학습), "본 서비스" = 반복 회차 3-fold 교차검증.
- 학습이 없는 방법(random, BARO, 통계 방법)은 두 기준에서 값이 같다.
- 처음 보는 서비스에서 SentriX-model(0.958)과 통계 방법(0.943)의 차이는 통계적으로 확실하지 않다. 그래프에 신뢰구간을 같이 그린 이유다.

## 4. linux-v1 (직접 수집 데이터)

수집이 끝나고 `docs/METHOD-FREEZE-v2.md` 4절대로 평가한 뒤 추가한다. 평가 결과를 같은 형태로 읽는 함수를 `make_poster_figures.py`에 더하고, 같은 `draw_*` 함수를 `dataset="linux-v1"`로 호출하면 같은 모양의 그림이 나온다. linux-v1에서는 연결 지연·패킷 손실의 **연결 순위** 그림이 추가된다.
