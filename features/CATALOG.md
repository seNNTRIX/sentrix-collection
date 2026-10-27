# Feature catalog — v0

코드: `features/compute.py` · 계약: `docs/RE2OB-DECISIONS.md` · 원천별 adapter: `features/adapters/`

모든 feature는 **(window, 후보 서비스)** 단위로 계산한다. window는 30초, 10초 간격, 반열린 구간 `[start, start+30)`이다. 지표는 5초 간격으로 다시 샘플링해서 window당 표본이 최대 6개다.

## 이름 규칙

| 접두사 | 묶음 | 모델 입력 |
|---|---|---|
| `f_cm_` | core metric — 자기 정상 구간 대비 변화, limit 대비 비율 | 기본 |
| `f_ct_` | core trace — trace에서 계산한 호출률·오류·지연 변화 | 기본 |
| `f_opt_` | optional — 원래 크기(절대 수준), 기울기, p99 | R4 실험으로 결정 |
| `f_log_` | experimental — 로그 개수·오류 개수 | R4 실험으로 결정 |
| `f_nbr_` | experimental — 이웃 서비스 대비 상대 변화 | R4 실험으로 결정 |
| `meta_*`, `target` | 식별·라벨·시각 | **절대 입력 금지** |

`tests/test_features_re2ob.py`가 `f_` 열 이름에 서비스 이름·case·fold·시각 관련 단어가 없는지, `f_`가 아닌 열은 모두 `meta_` 또는 `target`인지 검사한다.

## 정상 구간 통계 (baseline)

- RE2-OB: 장애 시각 −720초 ~ −420초의 window(28개)로 중앙값·IQR을 계산한다. 이 window들은 학습 행에 넣지 않는다. 그래서 어떤 학습 행도 자기 자신이나 미래의 값으로 정규화되지 않는다.
- linux-v1: baseline 구간의 앞부분으로 같은 규칙을 적용한다(adapter 구현 시 확정).

변환 방법:
- **robust delta** = (x − 중앙값) / IQR. IQR이 0이면 (x − 중앙값)을 쓰고 `_zero_iqr` = 1로 표시한다(feature-schema.yaml 규칙).
- **log ratio** = log((x + ε) / (중앙값 + ε)). ε은 지연 1e-4초, 비율 1e-3/초다.

## core metric (`f_cm_`)

지표 6종: `cpu_cores`, `cpu_limit_ratio`, `mem_limit_ratio`, `net_rx_pkts`, `net_tx_pkts`, `net_drop_pkts`

| feature | 계산 | 단위 |
|---|---|---|
| `f_cm_<지표>_dmean` | window 평균의 robust delta | 없음 |
| `f_cm_<지표>_dmax` | window 최대값의 robust delta(정상 구간 중앙값·IQR 기준) | 없음 |
| `f_cm_<지표>_zero_iqr` | 정상 구간 IQR이 0이었는지 (1/0) | — |
| `f_cm_<지표>_n` | window 안의 실제 표본 수 (최대 6) | 개 |
| `f_cm_cpu_limit_ratio_mean` | CPU 사용 / CPU limit, window 평균 | 비율 |
| `f_cm_mem_limit_ratio_mean` | 메모리 working set / limit, window 평균 | 비율 |

limit 비율은 서비스끼리 의미가 같아서(1에 가까우면 포화) 절대값을 core에 둔다.

원천:
- RE2-OB: `metrics.csv`의 컨테이너 지표. CPU는 코어 × 100 단위라 100으로 나누고, limit = quota / 100000µs로 둔다. 네트워크는 이미 초당 값이다.
- linux-v1: cAdvisor rate 지표 + kube-state-metrics limit.

## core trace (`f_ct_`)

span 처리 규칙 (두 데이터 공통):
- **들어오는 호출(node)**: 부모가 없거나 부모가 다른 서비스인 span. 그 서비스가 요청을 받아 처리한 시간이다.
- **연결(edge) 호출**: 부모 span의 서비스 A ≠ 자식 span의 서비스 B이면 A→B 호출 1건. 지연은 **호출하는 쪽(부모, client) span의 시간**이다. 그래서 네트워크 지연이 들어간다.
- 오류: 상태 코드가 0이 아니면 오류. 값이 없으면 오류로 보지 않는다.
- 분위수는 표본이 충분할 때만: p50 5개, p90 20개, p99 100개 미만이면 NaN.

| feature | 계산 |
|---|---|
| `f_ct_mask` | 정상 구간에 들어오는 호출이 있었는지(trace 계측 여부) 1/0 |
| `f_ct_in_rate_lr` | 들어오는 호출 수/초의 log ratio |
| `f_ct_in_err` | 들어오는 호출 오류 비율 |
| `f_ct_in_err_d` | 오류 비율 − 정상 구간 중앙값 |
| `f_ct_in_p50_lr`, `f_ct_in_p90_lr` | 처리 시간 p50/p90의 log ratio |
| `f_ct_out_p90_lr` | 이 서비스가 **호출하는** 연결들의 client 지연 p90 log ratio 중 최대값 |
| `f_ct_out_err` | 나가는 연결 오류 비율 중 최대값 |
| `f_ct_in_edge_p90_lr` | 이 서비스로 **들어오는** 연결들의 client 지연 p90 log ratio 중 최대값 |

## optional (`f_opt_`)

| feature | 계산 | 주의 |
|---|---|---|
| `f_opt_<지표>_mean/max/std` | 원래 값 | **서비스 지문이 될 수 있음.** 서비스마다 평소 수준이 달라서, 이름 없이도 서비스를 알아볼 수 있다. RE2-OB는 대상 5개만 원인이라 이걸로 "원인이 될 수 없는 서비스"를 외울 위험이 있다 |
| `f_opt_<지표>_slope` | window 안 선형 기울기 (표본 3개 이상) | |
| `f_opt_in_p99_lr` | 처리 시간 p99 log ratio (span 100개 이상) | |

## experimental

| feature | 계산 |
|---|---|
| `f_log_rate_lr` | 로그 줄 수/초의 log ratio |
| `f_log_err_rate` | 오류 로그 수/초. 오류 = level이 error·warn 계열이거나 `error` 필드가 비어 있지 않음 |
| `f_log_err_rate_d` | 오류 로그 수/초 − 정상 구간 중앙값 |
| `f_nbr_cm_cpu_cores_dmean`, `f_nbr_cm_mem_limit_ratio_dmean`, `f_nbr_ct_in_p90_lr`, `f_nbr_ct_in_err_d` | 해당 feature 값 − 같은 window에서 이웃 서비스 값들의 중앙값. 이웃 = 정상 구간 trace에서 호출 관계가 있던 서비스(방향 무시) |

## 탐지용 표 (`detection.parquet`)

window 하나 = 행 하나. `f_cm_`·`f_ct_`·`f_log_`·`f_nbr_` feature(`_n`, `_zero_iqr`, `_mask` 제외)를 후보 서비스 전체에서 모아 `__max`, `__mean`으로 만든다.

## 알려진 위험

- **`f_ct_mask`와 trace 결측:** trace가 없는 서비스 4개(ad, cart, shipping, redis-cart)는 두 데이터 모두 원인 대상이 아니다. 그래서 "trace 없음 = 원인 아님"을 모델이 배울 수 있다. R4에서 후보를 trace 있는 서비스로 제한한 결과도 같이 본다.
- **RE2-OB 장애 강도:** CPU 장애 시 원인 서비스의 `cpu_cores` delta가 수백까지 커진다. linux-v1(CPU worker 4, delay 100 ms, loss 2%)에서는 훨씬 작을 수 있다.
- **1초 → 5초 다시 샘플링:** 5초 안의 마지막 값만 쓴다. RE2-OB 원본 rate의 계산 구간은 미확인이다.
