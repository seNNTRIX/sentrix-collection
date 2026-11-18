# RE2-OB ↔ linux-v1 차이 처리 결정

결정일: 2026-10-27 · 근거: `docs/RE2OB-INVENTORY.md`(R1) · 적용: R2 이후 모든 RE2-OB 작업과 R5 방법 고정 문서

이 문서는 R2 코드(`features/`)가 따르는 계약이다. 바꾸려면 이 문서를 먼저 고치고 이유를 남긴다.

## 1. 대상 서비스: RE2-OB는 emailservice, linux-v1은 paymentservice

- 주 모델은 서비스 이름을 쓰지 않는 공유 가중치 순위 모델이므로 **그대로 사용**한다. 후보는 두 데이터 모두 Online Boutique 서비스 11개(canonical 이름)다.
- 후보에서 제외: `loadgenerator`, `frontend-external`(입구 지표), `traceservice`·`health`(계측·헬스체크 호출), GKE 노드.
- 교차 평가는 **전체**와 **공통 4개 서비스(checkout, currency, productcatalog, recommendation)** 결과를 따로 보고한다.
- RE2-OB로 학습한 모델에 linux-v1의 paymentservice 사례는 "처음 보는 원인 서비스" 시험이 된다. 결과를 따로 표시한다.

## 2. Istio·노드 지표

- 주 모델은 **두 데이터에서 같은 종류의 원천으로 계산되는 feature만** 쓴다(공통 feature 계약).

| feature 종류 | RE2-OB 원천 | linux-v1 원천 | 주 모델 |
|---|---|---|---|
| CPU 사용 / limit 비율 | `metrics.csv` 컨테이너 CPU 카운터 + CPU quota | cAdvisor + kube-state-metrics | 사용 |
| 메모리 / limit 비율 | `metrics.csv` working-set + memory limit | 같음 | 사용 |
| 네트워크 송수신 패킷·drop | `metrics.csv` container-network-* | 같은 cAdvisor 지표 | 사용 |
| 서비스·연결 호출률, 오류율, 지연 p50/p90 | `traces.csv`에서 직접 계산 | Tempo trace에서 직접 계산 | 사용 (같은 코드) |
| 로그 오류 개수 | `logs.csv` | Loki | 실험 후 결정 |
| `simple_metrics.csv`의 latency·workload·error | RCAEval 가공값 (원천 미확인) | 없음 | 사용 안 함 |
| Istio 지표 | 있음 | 없음 | 사용 안 함 (RE2-OB 전용 상한 실험만) |
| 노드 지표 | GKE 다중 노드 | 단일 노드 | 사용 안 함 |

- CPU·메모리는 절대값 대신 **limit 대비 비율**과 **자기 정상 구간 대비 변화량**으로 쓴다.
- 지연·오류는 양쪽 모두 trace에서 같은 코드로 계산한다.

## 3. 장애 종료 시각 없음

- 근거: 확인한 20개 case(cpu·delay·loss·mem)에서 장애 효과가 장애 후 720초 끝까지 유지됐다. 효과가 최대에 이르기까지 1~2분 걸리는 경우가 있다.
- 라벨(RE2-OB):
  - 정상: 장애 시각 이전.
  - 전환(제외): 장애 시각 ~ +60초.
  - 장애 활성: 장애 시각 +60초 이후.
  - 회복: 없음. 회복 관련 과제는 linux-v1에서만 한다.
- **case 단위 순위 점수는 두 데이터 모두 장애 시각 +60초 ~ +300초 구간의 window로만 계산**한다(RE2-OB는 장애가 12분, linux-v1은 5분이라 구간을 맞춤).

## 4. 그 밖의 차이

| 차이 | 결정 |
|---|---|
| 측정 간격 1초 vs 5초 | RE2-OB 지표를 **5초 간격으로 다시 샘플링**(5초 구간의 마지막 값)한 뒤 window를 만든다. window당 표본 6개로 linux-v1과 같다 |
| RE2-OB 지표 단위 (R2에서 확인) | `metrics.csv`의 `*-total` 열은 누적 카운터가 아니라 **이미 rate로 가공된 값**이다(rate 계산 구간은 미확인). CPU는 "코어 × 100" 단위다(checkoutservice quota 20000 = 0.2코어, 장애 중 값 약 20). CPU limit 비율 = (값 / 100) / (quota / 100000)이고, CFS period는 쿠버네티스 기본값 100000µs로 가정한다(period 열이 없음). 네트워크는 초당 패킷 수다. 따라서 RE2-OB에서는 rate를 다시 계산하지 않는다 |
| 장애 강도 | RE2-OB가 훨씬 강하다(CPU가 limit까지, loss 때 frontend 지연 수십 초). 교차 평가 성능 차이의 원인 후보로 보고한다 |
| 대조 run·사용자 거래 기록 없음 | RE2-OB에는 사용자 영향 판정을 할 수 없다. 90 case 모두 영향 있는 장애로 간주하고, 이 가정을 결과에 적는다 |
| 결측 | 시각이 빈 행은 버린다. `nan`은 0으로 채우지 않고 mask로 표시한다 |
| 예외 폴더 | `checkoutservice_cpu/multi-source-data`는 제외. 유효 case 90개 |
| 정상 구간 통계(baseline) | 미래 데이터를 쓰지 않도록, 정상 구간의 **앞부분(RE2-OB는 장애 시각 −720초 ~ −420초)** 만으로 중앙값·IQR을 계산하고, 그 구간의 window는 학습 행에서 뺀다 |
| 환경 | GKE 다중 노드 vs k3s 단일 노드. 노드 지표를 쓰지 않으므로 영향은 작다고 보고 한계로 기록 |

## 5. 분할

- RE2-OB: 반복 번호 기준 3-fold. fold k의 평가 = 반복 k인 case 30개, 학습 = 나머지 60개.
- 같은 case의 window는 항상 같은 fold.

## 6. 처음 보는 원인 서비스 (R4 이후 추가)

- R4의 서비스 하나 빼기(LOSO)에서 LightGBM core가 currency·productcatalog에서 통계 기준선보다 낮았다. linux-v1의 paymentservice는 RE2-OB에서 원인으로 나온 적이 없으므로 같은 상황이다.
- 그래서 R5 고정 전에 R4b를 한다. 사전 등록: `experiments/20261027-re2ob-r4b/config.yaml`.
  - 주 기준은 LOSO Avg@5다. 반복 회차 CV는 천장이라 보조 조건으로만 쓴다.
  - 비교 대상은 4개다: core, 변화량 feature만(rel), rel+단조 제약, rel과 통계 기준선의 순위 평균.
  - 통계 기준선을 넘는 후보가 없으면 linux-v1의 주 방법은 stat_combined다.
- R4b는 R4 결과를 본 뒤 설계했다. 그래서 고른 변형의 LOSO 점수는 낙관적이고, 공정한 시험은 linux-v1이 맡는다.
- linux-v1에서는 어느 경우든 stat_combined를 같이 보고하고, paymentservice가 원인인 case를 따로 보고한다.
