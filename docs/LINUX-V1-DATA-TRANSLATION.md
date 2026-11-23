# linux-v1 데이터 번역 결정 (2026-11-16)

이 문서는 고정 방법(`docs/METHOD-FREEZE-v2.md`, 고정 커밋 `399d3d0`)을 linux-v1 데이터에 적용할 때 **데이터를 어떻게 읽는지**를 정한다. 방법(feature 정의, window, 라벨 규칙, 모델, 하이퍼파라미터)은 바꾸지 않는다.

- 근거: 206-40 데이터셋 생성기 설계 조사(2026-11-16, 코드·문서·parquet 스키마·시각 필드·정상 구간 로그 개수·용량만 읽음).
- 이 시점에 linux-v1의 feature 값·점수·순위는 보지 않았다. 로그는 정상 구간의 개수만 셌다. 그 이전에 본 로그 1건은 `experiments/20261116-log-semantic-r8/PREREG.md` 2절에 적었다.
- 이 문서는 데이터셋 생성기 구현·빌드 **전에** 커밋한다. 커밋 이후 바꾸는 것은 아래 "변경 기록"에 날짜·이유·커밋과 함께 덧붙인다.

## 1. 수집하지 않은 신호

| 신호 | 상태 | 처리 |
|---|---|---|
| `net_rx_pkts`, `net_tx_pkts` | linux-v1 export에 없음 (drop rate만 수집). Prometheus 보존 12시간이 지나 다시 받을 수 없음 | 원인 순위 rel 18개 중 `f_cm_net_rx_pkts_dmean/dmax`, `f_cm_net_tx_pkts_dmean/dmax` **4개는 linux-v1 전체에서 NaN**. RF 입력에서는 고정 규칙대로 NaN → 0. 탐지 집계 58개의 해당 `__max/__mean` 열도 NaN(LightGBM이 결측으로 다룸) |

- 영향: linux-v1에서는 이 4개가 항상 "정상과 차이 없음"으로 들어간다. 특히 Pod 장애에서 원인 Pod의 트래픽 중단 신호는 trace의 호출 수 감소(`f_ct_in_rate_lr`)로만 들어간다.
- **보조 분석 (결과 전 등록):** rx/tx 4개를 뺀 Random Forest **rel14**(나머지 설정은 고정 값 그대로)로 주 평가와 같은 분할·같은 case를 계산해 함께 보고한다. 주 결과는 고정 방법(rel18)이다. rel14는 이 결측이 결과를 얼마나 바꾸는지 보는 민감도 분석이며, 결과를 보고 주 방법을 rel14로 바꾸지 않는다.
  - A 방식(RE2-OB 최종 모델 그대로 적용)에서는 rel14 모델을 RE2-OB 90 case로 같은 절차로 학습해 적용한다.

## 2. 시각 정의

run 기록에 `effect_observed_at` 등의 이름이 그대로 없어 다음과 같이 만든다.

| 시각 | 정의 | 원천 |
|---|---|---|
| run_start | `workload_started_at` | `runtime.json` |
| **onset — CPU 과부하·네트워크 지연·패킷 손실** | `started_at` (Chaos 주입이 적용된 시각) | `fault-record.json` |
| **onset — Pod 장애** | 대상 서비스의 `kube_pod_container_status_ready`가 장애 시작 이후 처음 0이 되는 5초 격자 시각 | canonical metrics |
| Pod 장애 대체 규칙 | 장애 시간 안에 Ready=0이 한 번도 없으면 onset = `started_at`, `onset_source = "fallback_started_at"`으로 표시하고 개수를 보고 | |
| **onset — 트래픽 급증** | `started_at` (k6 급증 단계 시작, `timing_source`로 확인) | `fault-record.json` |
| injection | `injection_requested_at` | `fault-record.json` |
| removal | `ended_at` | `fault-record.json` |
| recovery | `recovery.transaction_observation.stable_at`. 없으면 null (회복 확인 전까지 `recovering`) | incident |
| 대조 run | 각 시각 = 대조 run의 run_start + (짝 장애 run의 시각 − 장애 run의 run_start) | |

- Pod onset의 해상도는 5초다.
- 라벨 구간은 `features/windows.py`의 `label_linux_v1`을 그대로 쓴다.

## 3. 지표 읽기

| 항목 | 결정 |
|---|---|
| CPU | 원시 카운터가 없어 저장된 rate[60s]를 쓴다 (고정 문서 v1 6.2절 규칙). build-summary에 기록 |
| 네트워크 drop | Pod 단위 지표(`container="POD"` 또는 빈 값)로만 존재한다. "POD/pause 컨테이너 제외" 규칙의 **예외**로 네트워크 지표만 Pod 단위 값을 쓴다 |
| 패킷 손실 2%의 drop 반영 | netem drop이 `container_network_*_dropped`에 잡히는지 미확인. 해석에 적는다 |
| export 허용 누락점 | `tolerated_missing_points_unix`의 시각은 NaN (forward-fill 금지) |

## 4. 표 구성

| 항목 | 결정 |
|---|---|
| 탐지 표 양성 | 적격 장애 run의 `fault_active` |
| 탐지 표 음성 | 모든 run의 `normal`, `sham_active`, `recovered` |
| 비적격 장애 run의 `fault_active` | 학습·AUROC에서 빼고 `meta_eligible = false`로 따로 보관 (경보율 보고용) |
| 적격 | data_valid = `validity.is_valid_run`, injection_valid = `injector_succeeded` and `removal_confirmed`, impact_confirmed = `impact.confirmed` |
| fold | 반복 번호(r01·r02·r03). 같은 pair의 장애·대조 run은 같은 fold |
| RE2-OB와 합칠 때 | 두 데이터의 fold 번호가 겹치므로 데이터 출처 열(`meta_dataset`)로 구분한다. case_id는 `lv1_` 접두 |
| 채택 시도 | pair마다 `pair_attempts.adopted_attempt`로 valid 시도 하나. 실패 시도 3개(#20·#32·#38 시도 1)는 제외 사유와 함께 기록 |

## 5. 알려진 해석 위험 (결과 후에 고치지 않는다)

- 회복 확인(`stable_at`)이 장애 제거 직후 0~3초라, CPU rate[60s]의 꼬리가 남은 window가 `recovered`(음성)로 들어간다. 오경보율 해석에 적는다. 라벨 규칙은 바꾸지 않는다.
- 내보낸 trace는 k6 거래 trace 위주다. 호출률 해석에 적는다.
- productcatalogservice는 로그가 없어 로그 feature가 항상 NaN이다. redis-cart는 로그가 거의 없다.
- 장애 구간 로그의 `error` 필드 존재는 확인하지 않았다.

## 변경 기록

- (커밋 후 변경 사항을 날짜·이유·커밋과 함께 이 아래에 덧붙인다)
- 2026-11-23, 데이터셋 생성기 구현(branch `dataset-linux-v1`, `features/adapters/linux_v1.py`, `features/build_linux_v1.py`). 위 규칙은 바꾸지 않았고, 문서에 없던 **구현 세부만** 빌드 전에 정해 적는다. 이 시점에도 linux-v1의 feature 값·점수·순위는 보지 않았다(run 2개로 파일 읽기와 열 이름만 확인).
  - CPU limit = `container_spec_cpu_quota / container_spec_cpu_period`(RE2-OB와 같은 방식), memory limit = `kube_pod_container_resource_limits{resource="memory"}`. CPU·메모리는 앱 컨테이너(container 라벨이 비어 있지 않고 `POD`가 아님)만 쓴다.
  - 한 서비스의 여러 series(컨테이너 교체 등)는 같은 시각끼리 합한다. 구성 요소(사용량·limit, rx·tx drop)는 같은 query 시각끼리만 결합하고 채우지 않는다. 5초 재표본은 RE2-OB 어댑터의 `resample`(구간 (g−5, g]의 마지막 값, 없으면 NaN).
  - Pod onset: `[started_at, ended_at]` 안에서 대상 서비스 앱 컨테이너 Ready의 시각별 최솟값이 0인 첫 표본 시각.
  - trace 오류 = status code `STATUS_CODE_ERROR`. 서비스 이름이 없는 span(k6 등)은 부모 결합 뒤 버린다.
  - 로그 오류 = JSON 본문 `severity`(없으면 `level`), 둘 다 없으면 Loki 라벨 `detected_level`이 RE2-OB 어댑터의 `ERROR_LEVELS`에 들거나(pino 숫자 레벨은 40 이상), JSON `error` 필드가 비어 있지 않음. 로그 원문(`message`)과 `labels_json`은 R8용으로 어댑터에서 보존한다.
  - 채택 시도: fault run incident가 있고 `is_valid_run` true, incident의 `control_run_id`가 그 시도의 control run이며 두 run 폴더가 같은 root에 있을 때 valid. audit `status.json`은 판정에 쓰지 않는다(#15는 기록 단계만 실패해 status.json이 failed).
  - 비적격 장애 run의 `fault_active` window는 `detection-ineligible.parquet`에 따로 둔다(`detection.parquet`에는 학습·AUROC용 양성·음성만).
  - case_id = `lv1_` + run ID(시도 접미 `-a2` 포함). 원인 순위 표에는 적격 장애 run의 `fault_active`만 넣고, 연결·급증 장애 행은 정답 0으로 남긴다(노드 보기·서술용, 학습은 CPU·Pod만 골라 쓴다).
  - 실제 데이터 확인: 허용 누락점(`tolerated_missing_points_unix`)이 있는 채택 run은 0개다(규칙은 구현·테스트함).
- 2026-11-23, 구현 보고 후 사용자 결정(빌드 전):
  - 비적격 장애 run의 `fault_active`는 `meta_eligible` 플래그만 다는 대신 **별도 파일** `detection-ineligible.parquet`에 둔다(승인).
  - 원인 순위 표 `ranking.parquet`에는 **적격 CPU 포화·Pod 장애 run의 `fault_active` × 후보 11개만** 둔다(window마다 정답 1개). 적격 연결(지연·손실)·급증 장애 run의 같은 행은 `ranking-nodeview.parquet`로 분리한다(정답 0, 노드 보기·서술용). 위 항목의 "연결·급증 장애 행은 정답 0으로 남긴다"를 대체한다.
