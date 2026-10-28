# 방법 고정 v2 — linux-v1 평가의 사전 계획서

이 문서는 linux-v1 데이터의 feature·점수·순위를 보기 **전에** 최종 방법을 다시 고정한다.

- v1(`docs/METHOD-FREEZE.md`, 고정 커밋 `e25855f`)에서 **바뀐 것만** 적는다. 여기 적지 않은 것은 모두 v1 그대로다(처리, 라벨, case 점수 구간, 연결 점수, 6.2절 데이터 번역, 부록 A 실시간 규칙).
- v1 규칙대로 v1 방법(V4)의 결과도 linux-v1에서 함께 보고한다.
- linux-v1 결과를 본 뒤 이 문서를 바꾸면 그 평가는 더 이상 공정하지 않다. 바꿔야 하면 v3로 만든다.

## 1. 바꾼 이유

- 2026-10-27, 모델 종류와 feature 묶음을 **처음부터 다시 정하기로** 결정했다(사용자 결정).
- 근거 실험(모두 결과 전 사전 등록):

| 실험 | 내용 | 사전 등록 | 결과 |
|---|---|---|---|
| R6 | 모델 5종(로지스틱, RF, LightGBM, XGBoost, CatBoost) × feature 3종 × 단독/통계 결합 = 후보 31개 | `3595be4` | `43f2dc5` |
| R6b | R6 모델들의 순위 평균 앙상블 | `e7114c6` | `43f2dc5` |
| R7 | 같은 기본 모델에 원래 값을 넣은 ablation (방법 선택에는 쓰지 않음) | `c90321a` | `b5e342d` |

- R6 규칙(처음 보는 서비스 LOSO Avg@5 1등과 차이 없는 후보 중 가장 단순한 것)으로 순위는 **RF rel18 단독**, 탐지는 **LightGBM all58**이 선택됐다. R6b 앙상블 중 이 둘을 확실히 이긴 것은 없었다.
- R6 사전 등록 전에 축소 스모크 테스트가 점수를 출력한 일이 있었다(`experiments/20261027-re2ob-r6-models/notes.md`).

## 2. 최종 방법

| 과제 | v1 | **v2** |
|---|---|---|
| 장애 탐지 (window) | LightGBM, rel 집계 36개 | **LightGBM, 탐지 집계 58개 전부** |
| 원인 서비스 순위 (cpu, pod) | V4: LightGBM LambdaRank rel18 + stat_combined 순위 평균 | **Random Forest, rel18 단독** |
| 원인 연결 순위 (delay, loss) | 통계 연결 점수 | 그대로 |
| 장애 종류 분류 | 고정하지 않음 | **하지 않음** (2026-10-27 결정, 범위에서 제외) |

### 2.1 원인 서비스 순위: Random Forest

| 항목 | 값 |
|---|---|
| 입력 | rel 18개 (v1 2.2절과 같음, `training/run_r4b.py` `rel_cols`) |
| 행 | (window, 후보 서비스). 정답 서비스 = 1, 나머지 = 0. 서비스 이름은 넣지 않는다 |
| 결측 | **NaN → 0** (rel feature에서 0 = 정상 구간과 차이 없음) |
| 모델 | scikit-learn 1.5.2 `RandomForestClassifier` |
| 고정 값 | **n_estimators 300, min_samples_leaf 100, max_features 0.5**, random_state 0, n_jobs 4 |
| window 점수 | `predict_proba`의 원인일 확률 |
| case 점수 | v1 4절 그대로 (onset+60~300초 window 점수 평균) |
| 고른 방법 | RE2-OB 90 case에서 원인 서비스 5개를 하나씩 빼는 LOSO, R6 grid 4개 중 평균 Avg@5 최대(0.962), 같으면 앞의 설정 |
| 최종 모델 | RE2-OB 90 case 전체로 학습: `experiments/20261028-re2ob-v2-freeze/models/ranker_rf.joblib` |

- R6의 바깥 fold 5개에서는 모두 `max_features sqrt`가 골라졌고, 90 case 전체로 고르면 `0.5`가 골라졌다. v1과 같은 절차(전체 데이터로 다시 고름)를 따라 `0.5`로 고정한다.

### 2.2 장애 탐지: LightGBM

| 항목 | 값 |
|---|---|
| 입력 | `detection.parquet`의 집계 58개 전부 (후보 11개에 걸친 max·mean). rel 외에 수준 값, 원래 오류율, 로그, 이웃 feature 집계를 포함한다 |
| 모델 | LightGBM 4.5.0 `LGBMClassifier` binary |
| 고정 값 | **num_leaves 15, n_estimators 300, min_child_samples 20**, learning_rate 0.05, random_state 0, deterministic, force_row_wise, n_jobs 4 |
| 고른 방법 | RE2-OB 반복 회차 3-fold, R6 grid 4개 중 평균 AUROC 최대(0.996), 같으면 앞의 설정 |
| 최종 모델 | `experiments/20261028-re2ob-v2-freeze/models/detector_lgbm.txt` |

- 파일 해시, 데이터 해시, 패키지 버전은 `experiments/20261028-re2ob-v2-freeze/frozen.json`, `pip-freeze.txt`에 있다.

### 2.3 v1 문구 정정

- v1 2.1절의 "`baseline_stats` window의 5초 표본으로 중앙값·IQR"은 코드와 다르다. 실제 코드(`features/compute.py` `_baseline`, `272e514`)는 `baseline_stats` **window 값들의 중앙값·IQR**을 쓴다. 고정 대상은 코드이며, v2도 코드 그대로다(v1 부록 A.7).

## 3. RE2-OB 성능 (out-of-fold, 90 case)

| 순위 방법 | 처음 보는 서비스 LOSO Avg@5 | 학습 때 본 서비스 반복 CV Avg@5 |
|---|---|---|
| random | — | 0.273 |
| BARO (RCAEval 공식) | — | 0.742 |
| stat_combined | 0.943 (0.916–0.967) | 0.943 |
| 기본 모델 + 원래 값 (RF raw18, R7) | 0.844 (0.778–0.902) | 0.987 |
| V4 (v1 방법, R6 재실행) | 0.960 (0.933–0.980) | 0.981 |
| **RF rel18 (v2)** | **0.958 (0.931–0.978)** | **0.998 (0.993–1.000)** |

| 탐지 방법 | AUROC |
|---|---|
| stat_metric | 0.951 (0.928–0.969) |
| LightGBM rel 집계 36개 (v1) | 0.984 (0.964–0.997) |
| **LightGBM 집계 58개 (v2)** | **0.996 (0.988–1.000)** |

짝지은 비교 (Avg@5, 95% CI; R6 사후 계산 포함):
- RF rel18 − stat_combined: LOSO +0.014 (−0.013~0.042) **차이 없음**, 반복 CV +0.055 나음
- RF rel18 − V4: LOSO −0.002 (−0.023~0.017) 차이 없음, 반복 CV +0.017 (0.004~0.031) 나음
- RF rel18 − RF raw18 (R7, 사전 등록 주 질문): LOSO +0.113 (0.062~0.171) 나음

## 4. linux-v1 평가 (v1 6.3절에서 바뀐 것)

- **주 방법**: 탐지 = 2.2절 LightGBM, 노드 원인 순위 = 2.1절 RF. 연결 원인 순위는 v1 그대로다.
- **B 방식 [주 결과]**: 2절의 고정 값을 그대로 쓰고 다시 고르지 않는다. 학습 데이터 구성은 v1 6.3절과 같다(RE2-OB + linux-v1 학습 fold).
- **A 방식 [보조 결과]**: 2절의 최종 모델 파일을 linux-v1 전체에 그대로 적용한다.
- **함께 보고하는 비교 행** (주 방법과 같은 분할·같은 case로 계산하고, 결과를 보고 주 방법을 바꾸지 않는다):

| 과제 | 주 방법 | 비교 |
|---|---|---|
| 탐지 | LightGBM 집계 58개 | v1 탐지기(LightGBM rel 집계 36개, v1 고정 값), stat_metric |
| 노드 원인 순위 | RF rel18 | **V4 (v1 방법, v1 고정 값)**, stat_combined, random |
| 연결 원인 순위 | 통계 연결 점수 | random |

- 주 방법과 V4는 짝지은 case bootstrap 차이로 비교한다. paymentservice가 원인인 case는 따로 보고한다.
- 탐지 운영 기준점(정상 window 점수 95번째 백분위, 2개 연속)과 보고 방식은 v1 그대로다.

### 4.1 장애 종류별 원인 찾기 담당

근거: `campaigns/linux-v1/campaign-plan.yaml`, `campaigns/linux-v1/fault-params.yaml`(frozen 2026-10-23), v1 4절·6.3절.

**장애 주입과 정답**

| 장애 | 주입 방법과 강도 | 대상 (5개씩) | case 수 | 정답 형식 | RE2-OB에 있나 |
|---|---|---|---|---|---|
| CPU 포화 | Chaos Mesh, 대상 컨테이너에 CPU 부하 worker 4개, 부하 100%, 5분 | 서비스: checkoutservice, productcatalogservice, currencyservice, recommendationservice, paymentservice | 5 × 반복 3 = 15 | 서비스 이름 | 있음 (paymentservice는 RE2-OB에서 원인으로 나온 적 없음) |
| Pod 장애 | Chaos Mesh pod-failure, 대상 Pod 동작 불능, 5분 | 서비스: 위와 같은 5개 | 15 | 서비스 이름 | 없음 |
| 연결 지연 | Chaos Mesh NetworkChaos, 호출 경로 하나(ClusterIP 포함)에만 +100 ms, jitter 10 ms, correlation 0, 5분 | 연결: frontend→productcatalogservice, frontend→currencyservice, frontend→recommendationservice, recommendationservice→productcatalogservice, checkoutservice→paymentservice | 15 | 연결 `src->dst` | 서비스 단위로만 있음 (연결 정답 없음) |
| 패킷 손실 | 같은 방식, 호출 경로 하나에만 손실 2%, correlation 0, 5분 | 연결: 위와 같은 5개 | 15 | 연결 `src->dst` | 서비스 단위로만 있음 |
| 트래픽 급증 | k6 부하를 평소 0.4C(2.4 tx/s)에서 0.8C / 1.0C / 1.33C(4.8 / 6 / 8 tx/s)로 5분 | 부하 3단계 | 3 × 반복 3 = 9 | 특정 원인 없음 | 없음 |

- 모든 장애 run에는 같은 onset·구간 길이의 대조 run이 짝으로 있다(69쌍, 138 run).
- 원인 찾기 평가는 적격 case(data_valid, injection_valid, impact_confirmed)만 쓴다. 적격이 아닌 장애 run은 탐지 결과에 따로 표시한다(v1 6.3절).

**원인 찾기 방법과 평가**

| 장애 | 원인 찾기 방법 | 후보 | 학습 데이터 (B 방식) | 평가 지표 | 함께 보고 | 알려진 위험 |
|---|---|---|---|---|---|---|
| CPU 포화 | Random Forest 서비스 순위 (2.1절) | 서비스 11개 | RE2-OB 90 case + linux-v1 학습 fold의 CPU·Pod case | AC@1, AC@3, Avg@5, MRR | V4, stat_combined, random | 장애 강도가 RE2-OB보다 약하다. paymentservice 원인 case는 A 방식에서 처음 보는 서비스다 |
| Pod 장애 | Random Forest 서비스 순위 (2.1절) | 서비스 11개 | 위와 같음. RE2-OB에 없어 linux-v1 학습 fold에서만 배운다 | 위와 같음 | 위와 같음 | 지표가 끊기면 NaN → 0으로 읽힌다(5절). A 방식에서는 한 번도 못 본 장애다 |
| 연결 지연 | 규칙 기반 연결 점수 (v1 4절, `evaluation/edge_rank.py`) | 그 case의 `baseline_stats`에 client p90이 있던 연결 전부. 정답 연결이 없으면 꼴찌 | 학습 없음 | 연결 순위의 AC@1, AC@3, Avg@5 | random(후보 연결 수 기준). 보조: 노드 보기(RF 서비스 순위에서 양 끝 중 하나 / 출발만 / 도착만) | 규칙이 검증 없이 고정됐다. 정답 연결 5개 중 3개가 frontend 출발이라 노드 보기가 쏠릴 수 있다. 30초 window에 호출이 20개 미만인 연결은 p90이 NaN이다 |
| 패킷 손실 | 규칙 기반 연결 점수 (지연·오류 백분위 중 큰 쪽) | 위와 같음 | 학습 없음 | 위와 같음 | 위와 같음 | 2% 손실은 오류보다 재전송 지연으로 주로 나타나 신호가 약할 수 있다 |
| 트래픽 급증 | 원인 순위 평가 안 함 | — | — | 탐지만 (경보율) | RF 서비스 순위에서 frontend의 순위(서술) | 0.8C 단계는 영향이 확인되지 않을 수 있다 |

**모든 장애에 공통인 탐지**

| 항목 | 내용 |
|---|---|
| 방법 | LightGBM 이진 분류기, window당 집계 58개 (2.2절) |
| 학습 데이터 (B 방식) | RE2-OB 탐지 window + linux-v1 학습 fold window. 양성: 적격 장애 run의 `fault_active`. 음성: 모든 run의 `normal`, `sham_active`, `recovered` |
| 평가 | window 단위 AUROC·AUPRC, 적격 장애 run의 경보율, 대조 run의 오경보율 |
| 함께 보고 | v1 탐지기(LightGBM rel 집계 36개), stat_metric |

- **연결 단위 학습 모델은 시도하지 않는다.** 장애를 건 연결이 5개(반복 3회, 지연·손실 각 15 case)뿐이라, 처음 보는 연결로 일반화되는지 학습·검증하기에 데이터가 부족하다. 연결 수를 늘린 데이터셋 확장은 향후 과제로 둔다.

## 5. 새로 적어 두는 위험 (결과 후에 고치지 않는다)

v1 6.4절의 위험은 모두 그대로 유효하고, 다음을 더한다.

- **처음 보는 서비스**: RF rel18은 RE2-OB LOSO에서 stat_combined보다 확실히 낫지 않았다. A 방식의 paymentservice case에서 통계 방법이나 V4보다 낮을 수 있다.
- **pod_failure와 NaN → 0**: pod가 죽어 컨테이너 지표가 끊기면 NaN이 되고, RF에서는 0(정상과 차이 없음)으로 바뀐다. 이 경우 RF는 trace 신호(호출률 급감, 호출자 쪽 지연·오류)에 의존하게 된다. v1 V4(LightGBM)는 NaN을 결측으로 다뤘다. RE2-OB에 pod 장애가 없어 미리 확인하지 못했다.
- **탐지 feature 58개**: 수준 값·로그·이웃 feature 집계를 포함한다. 탐지는 처음 보는 서비스 시험(LOSO)을 하지 않았다. 로그 feature는 linux-v1 Loki 로그로 계산하며, 로그가 없으면 NaN이다.
- **선택 편향**: v2는 R3~R5 결과를 본 뒤 후보 31개 중에서 골랐다. RE2-OB 점수는 낙관적이며, 공정한 시험은 linux-v1이 맡는다.

## 6. 고정 기록

- 고정 커밋: (commit 후 기록)
- 이 시점에 linux-v1 정식 데이터의 feature·점수·순위는 하나도 보지 않았다. 수집 상태와 적격 여부(valid, impact)만 확인했다.
- 고정 이후 바뀌는 것은 모두 이 절 아래에 날짜·이유·커밋과 함께 덧붙인다.
