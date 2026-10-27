# 방법 고정 (R5) — linux-v1 평가의 사전 계획서

이 문서는 linux-v1 데이터를 보기 **전에** 최종 방법과 평가 계획을 고정한다.

- linux-v1 결과를 본 뒤 여기 적힌 것을 바꾸면 그 평가는 더 이상 공정하지 않다.
- 바꿔야 하면 새 버전(v2)으로 만든다. v1(이 문서)의 결과와 v2의 결과, 바꾼 이유를 모두 보고한다.

근거 실험:

| 단계 | 기록 | 결과 전 사전 등록 |
|---|---|---|
| R3 기준선 | `experiments/20261027-re2ob-baselines` | — |
| R4 모델 비교 | `experiments/20261027-re2ob-r4` | `8b27f87` |
| R4b 처음 보는 원인 서비스 | `experiments/20261027-re2ob-r4b` | `70960a9` |
| R5 최종 모델 | `experiments/20261027-re2ob-r5-freeze/` (`frozen.json`, `models/`) | — |

## 1. 최종 방법 한눈에

| 과제 | 방법 | 학습 |
|---|---|---|
| 장애 탐지 (window) | LightGBM 이진 분류, rel 집계 feature 36개 | RE2-OB |
| 원인 서비스 순위 (노드 장애) | **V4**: rel 18개 LightGBM LambdaRank 점수와 stat_combined의 case 단위 순위 평균 | RE2-OB |
| 원인 연결 순위 (연결 장애) | 통계 연결 점수(학습 없음, 4절) | 없음 |
| 장애 종류 분류 | 고정하지 않음(탐색 결과로만 보고) | — |

## 2. 입력과 feature

### 2.1 공통 처리 (바꾸면 안 됨)

| 항목 | 값 |
|---|---|
| 샘플링 | 5초 격자로 맞춤. 5초 구간의 마지막 값을 쓴다 |
| window | 30초 길이, 10초 간격. 반열린 구간 [시작, 끝)이고, 장애 시각(onset)에 window 시작이 맞춰진다 |
| 정상 구간 통계 | `baseline_stats` window의 5초 표본으로 중앙값·IQR을 구한다. 이 window는 학습 행에서 뺀다 |
| robust delta | (x − 중앙값) / IQR. IQR = 0이면 x − 중앙값 |
| log ratio | log((x + ε) / (중앙값 + ε)). ε은 지연 1e-4초, 호출률 1e-3/초 |
| 분위수 최소 표본 | p50은 5개, p90은 20개. 모자라면 NaN |
| 결측 | 0으로 채우지 않고 NaN으로 둔다. LightGBM이 NaN을 그대로 다룬다 |
| 금지 입력 | 서비스 이름, case ID, 절대 시각, 장애 시각, 후보 위치(`features/schema.py` FORBIDDEN_NAME_PARTS) |

계산 코드는 `features/compute.py`(R2, `272e514`)이고, 이 코드는 바꾸지 않는다. 정의는 `features/CATALOG.md`에 있다.

### 2.2 순위 feature: rel 18개 (자기 정상 구간 대비 변화량만)

| 이름 | 계산 | 원천 |
|---|---|---|
| `f_cm_<지표>_dmean` (6) | window 평균의 robust delta | 컨테이너 지표 |
| `f_cm_<지표>_dmax` (6) | window 최대값의 robust delta | 컨테이너 지표 |
| `f_ct_in_rate_lr` | 들어오는 호출 수/초의 log ratio | trace |
| `f_ct_in_err_d` | 들어오는 호출 오류 비율 − 정상 구간 중앙값 | trace |
| `f_ct_in_p50_lr`, `f_ct_in_p90_lr` | 처리 시간 p50/p90의 log ratio | trace(server span) |
| `f_ct_out_p90_lr` | 나가는 연결 client 지연 p90 log ratio의 최대값 | trace(client span) |
| `f_ct_in_edge_p90_lr` | 들어오는 연결 client 지연 p90 log ratio의 최대값 | trace(client span) |

`<지표>`는 6가지다: `cpu_cores`, `cpu_limit_ratio`, `mem_limit_ratio`, `net_rx_pkts`, `net_tx_pkts`, `net_drop_pkts`.

**뺀 것과 이유:** 수준·표본 수·표시 값(`_mean`, `_n`, `_zero_iqr`, `f_ct_mask`, `f_ct_in_err`, `f_ct_out_err`)과 로그·이웃·optional feature를 뺐다.
- 수준 값 때문에 feature만으로 서비스를 98.6% 알아볼 수 있었다.
- 그 결과 처음 보는 원인 서비스에서 성능이 떨어졌다(R4b).
- 로그·이웃·optional feature는 R4에서 효과가 없었다.

### 2.3 탐지 feature: rel 집계 36개

- rel 18개를 window마다 후보 11개에 걸쳐 max와 mean으로 모은 것이다(`detection.parquet`의 `<feature>__max`, `__mean`).
- 순위와 같은 이유로 수준 값 집계는 쓰지 않는다. 이 선택은 아래 결과를 보기 전에 정했다.

## 3. 모델, 하이퍼파라미터, seed

| | 순위 (V4의 학습 부분) | 탐지 |
|---|---|---|
| 모델 | LightGBM 4.5.0 `LGBMRanker`, objective `lambdarank`. query = 한 case의 한 window | LightGBM 4.5.0 `LGBMClassifier`, binary |
| 공통 | learning_rate 0.05, random_state 0, deterministic, force_row_wise, n_jobs 4 | 같음 |
| 고정 값 | **num_leaves 15, n_estimators 100, min_child_samples 100** | **num_leaves 31, n_estimators 300, min_child_samples 20** |
| 고른 방법 | RE2-OB 90 case에서 원인 서비스 5개를 하나씩 빼는 LOSO, 후보 8개 중 평균 Avg@5 최대(0.949), 같으면 작은 모델 | RE2-OB 반복 회차 3-fold, 후보 8개 중 평균 AUROC 최대(0.993), 같으면 작은 모델 |
| 최종 모델 | RE2-OB 90 case 전체로 학습: `models/ranker.txt` | `models/detector.txt` |

- **고른 방법이 서로 다른 이유:** 순위의 핵심 위험은 처음 보는 원인 서비스이므로 LOSO로 고른다. 탐지는 서비스 단위 위험이 아니므로 반복 회차로 고른다.
- 파일 해시와 데이터 해시는 `frozen.json`에 있다(feature 표 sha256, 모델 sha256, 패키지 버전).

**V4 순위 평균 규칙**
- case마다 후보 11개에 대해 두 순위를 매긴다.
  - LightGBM case 점수의 순위
  - stat_combined case 점수의 순위
- 순위는 큰 점수가 1등이고, 동점은 평균 순위, NaN은 꼴찌다.
- 최종 점수는 −(두 순위의 평균)이다.

**stat_combined 정의 (R3, 학습 없음)**
1. window마다 metric 점수와 trace 점수를 구한다.
   - metric 점수 = 지표 6종 `dmean` 절댓값의 최대값
   - trace 점수 = `|in_p90_lr|`과 `|in_edge_p90_lr|` 중 최대값
2. 두 점수를 각각 같은 window 후보들 사이의 백분위 순위로 바꾼다.
3. 둘 중 큰 값을 그 window의 점수로 쓴다.

## 4. case 점수와 평가

**case 점수 (노드)**
- 각 후보의 case 점수 = `fault_active` window 중 시작이 onset+60초 이상, onset+300초 미만인 window의 점수 평균(`evaluation/aggregate.py`, R3).
- linux-v1에서 `fault_active`는 장애 제거 시각에서 끝나므로, 구간은 제거 시각에서 자동으로 잘린다.

**연결 점수 (연결 장애, `evaluation/edge_rank.py`)**
- **후보:** 그 case의 `baseline_stats` window에서 client p90이 있는 caller→callee 연결
- **window 점수:** 같은 window의 후보 연결들 사이에서 두 값의 백분위 순위를 구하고, 큰 쪽을 쓴다.
  - |log((p90 + ε) / (정상 중앙값 + ε))|
  - 오류 비율 − 정상 중앙값
- **case 점수:** 노드와 같은 구간의 평균
- 정답 연결이 후보에 없으면 꼴찌로 친다.
- 이 규칙은 RE2-OB에 연결 정답이 없어서 **검증 없이** 고정한다.

**지표 (R3, `evaluation/metrics.py`)**
- AC@k, Avg@5: RCAEval 논문 v5 §4.2 정의. 동점은 기대 순위, NaN은 꼴찌.
- 보조 지표: MRR
- 신뢰구간: case 단위 bootstrap 95%(2000회, seed 0)
- 비교: 짝지은 case bootstrap 신뢰구간이 0을 포함하지 않을 때만 "낫다/나쁘다"
- 탐지: window 단위 AUROC, AUPRC. case 단위 bootstrap

## 5. RE2-OB 최종 성능 (out-of-fold, 90 case)

| 순위 방법 | 반복 회차 CV Avg@5 | 처음 보는 서비스 LOSO Avg@5 |
|---|---|---|
| random | 0.273 | — |
| BARO (RCAEval 공식 재현) | 0.742 | — |
| stat_combined | 0.943 (0.916–0.967) | 0.943 |
| LightGBM core 35개 (R4 후보) | 0.996 | 0.889 (통계보다 나쁨) |
| LightGBM rel 18개 | 0.996 | 0.942 |
| **V4 (고정)** | **0.981 (0.970–0.991)**, 통계보다 +0.038 | **0.959 (0.933–0.979)**, 통계보다 +0.016 (0.001–0.030) |

| 탐지 방법 | AUROC |
|---|---|
| stat_metric (R3) | 0.951 (0.930–0.969) |
| LightGBM core (R4) | 0.984 |
| **LightGBM rel 집계 (고정)** | **0.993 (0.986–0.998)**, AUPRC 0.995 |

- 위 숫자는 fold마다 하이퍼파라미터를 다시 고른 out-of-fold 값이다. 3절의 최종 모델 자체의 RE2-OB 점수가 아니다.
- RE2-OB는 강한 장애가 12분 이어지는 데이터라 천장에 가깝다. linux-v1에서 낮아지는 것은 예상된 결과다.

## 6. linux-v1 적용

### 6.1 바꾸면 안 되는 것
- 2.1~2.3의 처리·feature 목록
- 3절의 모델과 고정 값, V4 규칙, stat_combined 정의
- 4절의 case 점수 구간(onset+60~300초), 연결 점수 규칙, 지표와 비교 규칙
- 아래 6.3의 평가 설계와 주 결과 지정

### 6.2 데이터 차이 때문에 조정하는 것 (데이터 번역만, 결과 보기 전에 확정)

| 차이 | 조정 |
|---|---|
| 측정 간격 | RE2-OB는 1초, linux-v1은 Prometheus 5초. 둘 다 5초 격자이므로 같다 |
| CPU·네트워크 단위 | RE2-OB는 이미 rate다. linux-v1은 원시 카운터가 저장돼 있으면 5초 차분으로 rate를 구하고, 없으면 저장된 rate[60s]를 쓰고 그 사실을 기록한다 |
| 서비스 이름 | pod → canonical 이름(`frontend`, `redis-cart`). 같은 `CANDIDATES` 11개 |
| onset | `effect_observed_at`. pod_failure는 첫 Ready=false, traffic_surge는 부하 증가 시작 |
| 정상 구간 | 처음 180초는 warmup으로 제외한다. RE2-OB는 300초 통계 + 420초 정상이지만, linux-v1은 정상 구간이 240~540초라 비율을 맞출 수 없어 이렇게 나눈다 |
| 라벨 | `features/windows.py` `label_linux_v1` (아래 표). 테스트 `tests/test_linux_v1_labels.py` |
| 대조 run | 짝인 장애 run의 시각을 그대로 쓰는 가짜 장애 시각. 장애 구간은 `sham_active`로, 정상 window로 다룬다 |
| 연결 장애 정답 | 노드가 아니라 `src->dst` 연결이다. 연결 점수(4절)로 평가한다 |
| RE2-OB에 없는 장애 | pod_failure는 노드 순위에 그대로 넣는다. traffic_surge는 원인 순위 주 결과에서 빼고 탐지만 평가한다(6.3) |
| 장애 강도 | RE2-OB보다 약하다. 조정하지 않고 결과 해석에 적는다 |

linux-v1 정상 구간과 라벨:

| 구간 | 라벨 |
|---|---|
| [warmup 끝, onset−120초) | `baseline_stats` |
| [onset−120초, onset) (주입 관측 전까지) | `normal` |
| 주입 관측 ~ onset+60초에 걸치는 window | `transition`, 제외 |
| onset+60초 ~ 제거 | `fault_active` |
| 제거 ~ 회복 확인 | `recovering`, 제외 |
| 회복 확인 이후 | `recovered`, 정상 |
| 경계를 넘는 window | 제외 |

### 6.3 평가 설계 (사전 등록)

대상:
- **적격 case:** data_valid, injection_valid, impact_confirmed가 모두 참인 장애 run
- 적격이 아닌 장애 run은 탐지 결과에 따로 표시한다.

**두 가지 학습 방식**
- **B. linux-v1 반복 회차 3-fold [주 결과]** (`campaign-plan.yaml`의 평가 규칙)
  - 3절의 고정 값을 그대로 쓰고 다시 고르지 않는다.
  - 순위 학습 데이터 = RE2-OB 90 case + 학습 fold의 linux-v1 노드 장애 case(cpu_saturation, pod_failure). 가중치는 두지 않는다.
  - 탐지 학습 데이터 = RE2-OB 탐지 행 + 학습 fold의 linux-v1 window.
    - 양성: 적격 장애 run의 `fault_active`
    - 음성: 모든 run의 `normal`, `sham_active`, `recovered`
  - 같은 pair의 장애 run과 대조 run은 같은 fold에 둔다.
- **A. 그대로 옮기기 [보조 결과]:** 3절의 최종 모델을 linux-v1 전체에 적용한다. linux-v1로 학습하지 않는다. paymentservice는 여기서 처음 보는 원인 서비스다.

| 과제 | 대상 | 주 방법 | 함께 보고 |
|---|---|---|---|
| 탐지 | 모든 run의 window | LightGBM rel 집계 | stat_metric |
| 노드 원인 순위 | cpu_saturation·pod_failure 적격 case (최대 30) | V4 | rel LightGBM 단독, stat_combined, random |
| 연결 원인 순위 | network_delay·packet_loss 적격 case (최대 30) | 통계 연결 점수 | random(후보 연결 수 기준) |
| 연결 장애의 노드 보기 | 위와 같은 case | V4 노드 순위 | 아래 참고 |
| surge | traffic_surge case (9) | 탐지만 | V4에서 frontend의 순위(서술) |

**연결 장애의 노드 보기 (보조)**
- 양 끝 서비스 중 하나라도 top-k에 들면 맞음으로 친다. 관대한 기준이며, 논문 정의 그대로가 아니다.
- 도착 서비스만 정답, 출발 서비스만 정답으로 본 결과를 함께 보고한다.
- 연결 5개 중 3개가 frontend에서 출발하는 쏠림도 같이 적는다.

**탐지의 운영 기준점**
- 학습 데이터의 정상 window 점수 95번째 백분위(FPR 5%)를 문턱으로 둔다.
- run 경보 = onset+60초 ~ 제거 구간에서 문턱을 넘는 window가 2개 연속일 때. 대조 run은 같은 가짜 구간을 쓴다.
- 보고 항목은 두 가지다.
  - 적격 장애 run의 경보율
  - 대조 run의 오경보율

**보고 방식**
- 모두 out-of-fold case 지표, fold 평균±표준편차, case bootstrap 95% CI로 보고한다.
- 장애 종류별로 나눠 보고한다. 원인 서비스별로 나누되, **paymentservice가 원인인 case는 따로** 보고한다.
- V4 대 stat_combined는 짝지은 차이로 비교한다. 같은 비교를 A·B 방식 모두에서 한다.

### 6.4 미리 적어 두는 위험 (결과 후에 고치지 않는다)
- **pod_failure:** 컨테이너 지표가 끊기거나 0으로 떨어진다.
  - LightGBM은 RE2-OB에서 이런 장애를 본 적이 없다.
  - stat_combined는 지표가 모두 NaN인 후보를 꼴찌로 둔다.
  - 두 경우 모두 잘 맞히지 못할 수 있다.
- **처음 보는 원인 서비스:** A 방식에서 paymentservice는 처음 보는 원인 서비스다. RE2-OB LOSO 결과로 보면 V4는 통계 방법과 비슷하거나 조금 나은 정도가 예상된다.
- **장애 강도:** RE2-OB보다 약해서 모든 점수가 낮아질 수 있다.
- **rate[60s]:** 원시 카운터가 없으면 30초 window 안의 변화가 무뎌진다.
- **연결 점수 규칙:** 검증 없이 고정한 규칙이다.
- **노드 보기의 쏠림:** 연결 정답의 출발 서비스가 frontend에 쏠려 있다.
- **환경:** 단일 replica, k3s 단일 노드로, RE2-OB의 GKE 다중 노드와 다르다.

## 7. linux-v1 adapter

- 인터페이스와 할 일 목록은 `features/adapters/linux_v1.py`에 있다.
- `Case`에는 linux-v1 전용 필드(kind, target_kind, pair_id, 시각들, eligible)를 기본값과 함께 추가했다. RE2-OB 코드는 영향을 받지 않는다.
- 실제 구현은 정식 pair 데이터가 나온 뒤에 한다.
- adapter는 데이터 번역만 한다. 구현 중 확인은 신호 범위, NaN 비율, window 수까지만 하고, 점수나 순위는 보지 않는다.

## 8. 고정 기록

- **고정 커밋: `e25855f5af866baedb91c9afb014d394f2091024`** (2026-10-27, branch `research-re2ob`).
  - 이 문서, 고정 코드, `experiments/20261027-re2ob-r5-freeze/`(모델·해시)가 모두 들어간 상태다.
  - 바로 앞 커밋 `9f2369b`에 같은 내용이 처음 들어갔다. 그때는 모델 파일의 줄바꿈이 git 변환으로 바뀌어 `frozen.json` 해시와 맞지 않았다. `e25855f`에서 원래 바이트 그대로 다시 저장했다(`.gitattributes`).
- 이 시점에 linux-v1 정식 데이터의 feature·점수·순위는 하나도 보지 않았다.
- 고정 이후 바뀌는 것은 모두 이 절 아래에 날짜·이유·커밋과 함께 덧붙인다.

## 부록 A. 실시간 기준 구간 규칙 (초안, 2026-10-27)

> 상태: **초안.** 아직 commit하지 않았다. 확정하면 이 줄을 지우고 커밋 해시를 A.7에 적는다.

### A.1 왜 필요한가

- 1~6절의 정상 구간 통계(`baseline_stats`)는 **장애 시각(onset)을 기준으로** 잘라 정한다(RE2-OB −720~−420초, linux-v1 warmup 끝~onset−120초).
- 오프라인 평가에서는 이 방식이 맞다. onset 이전 데이터만 쓰고, RCAEval도 장애 시각을 주고 평가한다.
- 하지만 실시간 시스템(sentrix-core)은 onset을 모른다. 그대로 두면 학습 때와 실제 사용 때 feature 계산이 달라진다.
- 이 부록은 **실시간에서만** 쓰는 기준 구간 규칙이다. 1~6절의 방법·모델·주 결과는 바꾸지 않는다.

### A.2 원칙

1. 기준 구간은 **현재 시각만으로** 정한다. onset, 라벨, case 정보를 쓰지 않는다.
2. 경보가 없을 때만 기준 구간을 갱신한다. **경보가 울리면 기준 구간을 얼린다.** 장애 데이터로 기준이 오염되는 것을 막는다.
3. 구간의 모양(간격, 길이)은 오프라인 정의와 최대한 같게 둔다. 그래야 학습한 feature 분포와 맞는다.
4. 중앙값·IQR 계산과 feature 계산은 `features/compute.py`를 그대로 쓴다. 바뀌는 것은 "어느 window를 기준으로 넣는가"(`base_mask`) 하나뿐이다.

### A.3 값

| 이름 | 값 | 근거 |
|---|---|---|
| warmup | 시작 후 180초 | linux-v1 `LV1_WARMUP` |
| 간격 G | 120초 | linux-v1에서 `baseline_stats`는 onset−120초에서 끝난다. 장애가 지금 막 시작됐다면 오프라인과 같은 위치다 |
| 길이 L | 300초 | RE2-OB `baseline_stats` 길이(−720~−420초). linux-v1의 120~420초 범위 안에 있다 |
| 최소 길이 | 120초 | linux-v1 `baseline_stats`의 가장 짧은 경우(onset 420초 − warmup 180초 − 120초). 모자라면 해당 feature는 NaN |
| 경보 | 6.3절 문턱(학습 정상 window 점수 95번째 백분위)을 넘는 window 2개 연속 | 6.3절과 같다 |
| 경보 해제 | 문턱 아래 window 6개 연속(60초) | **새로 정한 값, 검증 없음** |
| RCA 구간 | 경보 첫 window 시작 ~ +240초, 해제되면 거기서 끊음 | 오프라인 case 점수 구간(onset+60~300초)과 길이를 맞춤 |

### A.4 절차

시각 t에 끝난 window마다 아래를 한다.

| 상태 | 기준 구간 | 하는 일 |
|---|---|---|
| **정상** | 시작이 [t − G − L, t − G) 안에 있고 끝이 t − G 이하인 window 중, warmup 이후이면서 정상 상태에서 계산된 것 | 기준 구간으로 feature 계산 → 탐지 점수. 2개 연속 문턱을 넘으면 **경보**로 바꾼다 |
| **경보** | 첫 초과 window 시작 시각을 t₀라 할 때, [t₀ − G − L, t₀ − G) 구간으로 **고정** | 같은 기준으로 feature 계산 → V4 노드 순위, 연결 점수. RCA 구간의 window 점수 평균을 결과로 낸다. 6개 연속 문턱 아래면 **회복**으로 바꾼다 |
| **회복** | 경보 때의 고정 구간을 그대로 쓴다 | 회복 이후 정상 window가 G + 120초 이상 쌓이면 **정상**으로 돌아간다. 그 전 window는 기준 구간에 넣지 않는다 |

- 중간 결과: 경보 중에는 window마다 그때까지의 평균 순위를 화면에 보여줄 수 있다. 공식 결과는 RCA 구간 전체 평균이다.
- 기준 구간에 값이 없는 후보(새로 뜬 pod 등)는 오프라인과 같이 NaN으로 두고 꼴찌로 친다.

### A.5 오프라인과 다른 점과 위험

- **탐지 지연이 G보다 길면** 고정 구간 끝부분에 장애 데이터가 섞일 수 있다. 천천히 시작하는 장애(메모리 누수 등)에서 그렇다.
- **천천히 변하는 추세:** 정상 상태에서 기준이 계속 따라가므로, 아주 느린 변화는 탐지되지 않을 수 있다. 206-39에서 기록한 메모리 누수가 그런 예다.
- **RCA 구간 시작:** 오프라인은 onset+60초부터 시작하지만, 실시간은 경보 시각부터 시작한다. 경보가 onset+60초보다 빠르거나 늦으면 점수에 쓰는 window가 달라진다.
- **경보 해제 규칙**은 RE2-OB(장애가 끝나지 않음)로 검증할 수 없다.
- **길이 L:** linux-v1 오프라인은 warmup 끝부터 onset−120초까지 전부(120~420초)를 쓰지만, 실시간은 최대 300초만 쓴다.
- **currency·payment 메모리 누수와 재시작** (근거: `docs/SETUP-REVIEW-20261016.md` 7.19)
  - 두 서비스는 부하가 없어도 약 21.5~22 MiB/h씩 메모리가 늘고, 512Mi limit 근처에서 약 22시간마다 exit 137로 재시작된다. OOM kill인지 liveness probe kill인지는 확인하지 못했다.
  - 수집에서는 #19부터 pair 시작 전에 두 Pod를 지우고 다시 띄운다(`campaigns/linux-v1/pre-pair-reset.yaml`). #1~#15(8 pair)는 초기화 없이 수집됐지만 run 도중 재시작은 없었다.
  - **실시간 데모에는 이런 pair 단위 초기화가 없다.** 오래 켜 두면 약 22시간마다 두 서비스 중 하나가 재시작되고, 탐지기는 이를 pod_failure와 같은 장애로 볼 수 있다. 원인 순위도 그 서비스를 1등으로 낼 것이다. 주입한 장애가 아니므로 데모에서는 오경보로 센다.
  - 메모리 증가 자체는 기준 구간 300초 동안 약 2 Mi로 작고, 정상 상태에서는 기준이 따라가므로 탐지에는 거의 드러나지 않는다(위 "천천히 변하는 추세"와 같은 이유).
  - 데모 대처는 이 부록에서 정하지 않는다. 후보는 두 가지다. ① 데모 시작 전과 일정 간격으로 같은 초기화를 한다. ② 재시작 시각(Pod 이벤트)을 기록해 두고 그 경보를 "알려진 재시작"으로 따로 표시한다. 어느 쪽이든 경보 자체를 숨기지는 않는다.
- **export 누락점** (근거: `docs/SETUP-REVIEW-20261016.md` 7.20, 2026-10-27부터 두 PC 공통)
  - 수집에서는 scrape 한 번 실패로 빠진 점을 60초 간격으로 3번 더 조회한다. 그래도 빠지고, 따로 떨어진 1점(5초)이면서 run grid의 0.5% 이하면 허용한다. 빠진 시각은 `export-manifest.json`의 `metrics.<group>.tolerated_missing_points_unix`와 `canonicalize-summary.json`의 `metrics.tolerated_missing_points_unix`에 남는다.
  - 오프라인(linux-v1 adapter): 이 목록의 시각은 5초 격자에서 **NaN으로 둔다.** 앞 값으로 채우지 않는다(`feature-schema.yaml` missingness `export_tolerated_gaps: missing`). 그 window는 표본이 6개가 아니라 5개가 되고, `features/compute.py`가 NaN을 건너뛰고 계산하므로 고정 코드는 바꾸지 않는다. 이 처리는 7절 adapter 할 일 목록에 넣는다.
  - 실시간: 같은 scrape 실패가 생기면 같은 방식(NaN, 앞 값으로 채우지 않음)으로 다룬다. 다만 실시간에는 60초 뒤 재조회가 없어서, 늦게 들어오는 점까지 빠진다. 그래서 오프라인보다 누락이 조금 많을 수 있다.
  - 10/26에 빠진 점은 `spanmetrics_duration_bucket` 묶음이었다. 고정 feature의 지연·오류 값은 spanmetrics가 아니라 trace에서 직접 계산하므로(`docs/RE2OB-DECISIONS.md` 2절), 이 묶음의 누락은 고정 feature에 직접 들어가지 않는다. 컨테이너 지표 묶음에서 빠지면 위 처리대로 그 window의 표본이 하나 줄어든다.

### A.6 확인 방법 (결과 보기 전에 등록)

1. **같은 계산인지 테스트:** 같은 window 집합을 기준으로 줬을 때, 실시간 경로와 `features/compute.py`의 feature 값이 같은지 확인하는 단위 테스트를 둔다.
2. **RE2-OB 재생 실험:** RE2-OB 90 case를 시간 순서대로 흘려 A.4 절차를 돌린다(경보 문턱은 6.3절 방식, 반복 회차 3-fold의 학습 fold로 정한다).
   - 보고: 경보율, onset 대비 경보 지연, 오경보(onset 이전 경보) 수, 실시간 V4 Avg@5와 5절 오프라인 값의 차이.
   - 차이가 커도 1~6절 방법은 바꾸지 않는다. 실시간 규칙(A.3 값)을 바꿔야 하면 새 버전으로 만들고 전후 결과를 둘 다 남긴다.
3. **linux-v1 보조 결과:** 6.3절 B 방식의 fold 모델로 같은 재생을 해서 "실시간 모드" 결과를 보조로 보고한다. 주 결과는 6.3절 그대로다.
   - 대조 run의 오경보율, 적격 장애 run의 경보율과 경보 지연, 노드·연결 순위를 보고한다.

### A.7 함께 발견한 것 (문구 확인 필요)

- 2.1절은 "`baseline_stats` window의 **5초 표본**으로 중앙값·IQR"이라고 적혀 있다.
- 실제 코드(`features/compute.py` `_baseline`)는 `baseline_stats` window들의 **window 값(평균 등)** 으로 중앙값·IQR을 구한다.
- 2.1절에 따르면 고정 대상은 코드(`272e514`)다. 그래서 코드는 그대로 두고, 2.1절 문구만 정정해야 한다. 정정 시점과 이유는 이 절 아래에 기록한다.
- 이 부록도 코드 기준(window 값)을 따른다.

고정 커밋: (미정, commit 후 기록)
