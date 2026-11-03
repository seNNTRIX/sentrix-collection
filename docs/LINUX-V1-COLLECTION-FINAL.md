# linux-v1 수집 최종 결과 (69 pair)

기준일: 2026-11-03 · 캠페인 `linux-v1`(seed 20261023, `campaigns/linux-v1/schedule.json` sha256 `d7fd8332…787f`)
근거: 206-40은 이 저장소(school-pc)의 `incidents/`·`audits/`·`runs/_campaign/linux-v1/decisions.yaml`, 206-39는 `origin/collect-206-39`(211f7c6)의 `incidents/`·`docs/pc/206-39.md`. 경위는 `docs/pc/206-40.md`, `docs/SETUP-REVIEW-20261016.md` 7.18~7.23.

**결론: schedule 69 pair 모두 valid pair 1개씩 확보. 제외 0, 중복 0, 누락 0.** impact 있음 54, 없음 15(모두 주입·해제 확인된 유효 무영향 표본).

## 합계 검산

| 구분 | shard | 수집 PC (environment_id) | pair | 비고 |
|---|---|---|---|---|
| 206-40 기본 | `206-40.json` | 206-40 | 35 | #20·#32는 시도 2 채택, #15는 `resolved_pairs` |
| 206-39 완료 | `206-39.json` | 206-39 | 18 | 206-39.json 34 pair 중 완료분 |
| 206-39에서 이관 | `206-40-b.json` | 206-40 | 15 | 206-39에서 시작 안 한 pair |
| #38 재시도 | `206-40-c.json` | 206-40 | 1 | 시도 1은 206-39에서 실패 |
| **합계** | | 206-40 51 + 206-39 18 | **69** | = schedule.json 69 |

- schedule 번호 1~69 대조: 중복 0, 누락 0, schedule에 없는 번호 0. pair_id 중복 0.
- 채택 run ID 138개(69 × fault·control) 모두 다르다. 실패 시도의 run ID(#20·#32 시도 1: 206-40, #38 시도 1: 206-39)와도 겹치지 않는다(재시도는 `-a2`).
- 69개 모두 injector succeeded, removal confirmed, run assessment valid, control_match valid, `is_valid_run: true`.
- impact 판정 endpoint는 모두 checkout. latency_increase 42, error_rate_increase 12, 없음 15.
- status: recovered 53, fault_active_no_impact 15, abnormal_impacted 1(#3, 회복 관측 fail).
- pair 순서: fault_then_control 35, control_then_fault 34.

## fault 종류 × 반복

| fault | r01 | r02 | r03 | 합계 | impact 있음 | impact 없음 |
|---|---|---|---|---|---|---|
| cpu_saturation | 5 | 5 | 5 | 15 | 9 | 6 |
| network_delay | 5 | 5 | 5 | 15 | 14 | 1 |
| packet_loss | 5 | 5 | 5 | 15 | 12 | 3 |
| pod_failure | 5 | 5 | 5 | 15 | 13 | 2 |
| traffic_surge | 3 | 3 | 3 | 9 | 6 | 3 |
| **합계** | 23 | 23 | 23 | 69 | 54 | 15 |

traffic_surge는 강도 L1·L2·L3 × 반복 3 = 9, 나머지는 원인 5개 × 반복 3 = 15.

## impact 없음 pair (15)

| # | pair_id | fault | 원인 | 반복 | 수집 PC | status |
|---|---|---|---|---|---|---|
| 2 | linux-v1-delay-checkout-payment-r02 | network_delay | checkoutservice→paymentservice | r02 | 206-39 | fault_active_no_impact |
| 7 | linux-v1-pod-recommendationservice-r01 | pod_failure | recommendationservice | r01 | 206-39 | fault_active_no_impact |
| 9 | linux-v1-cpu-paymentservice-r01 | cpu_saturation | paymentservice | r01 | 206-39 | fault_active_no_impact |
| 12 | linux-v1-pod-recommendationservice-r03 | pod_failure | recommendationservice | r03 | 206-40 | fault_active_no_impact |
| 23 | linux-v1-cpu-paymentservice-r03 | cpu_saturation | paymentservice | r03 | 206-40 | fault_active_no_impact |
| 25 | linux-v1-cpu-checkoutservice-r02 | cpu_saturation | checkoutservice | r02 | 206-40 | fault_active_no_impact |
| 26 | linux-v1-loss-checkout-payment-r02 | packet_loss | checkoutservice→paymentservice | r02 | 206-39 | fault_active_no_impact |
| 36 | linux-v1-surge-l1-r03 | traffic_surge | frontend 진입 부하 L1 | r03 | 206-39 | fault_active_no_impact |
| 37 | linux-v1-loss-checkout-payment-r01 | packet_loss | checkoutservice→paymentservice | r01 | 206-40 | fault_active_no_impact |
| 41 | linux-v1-surge-l1-r01 | traffic_surge | frontend 진입 부하 L1 | r01 | 206-40 | fault_active_no_impact |
| 47 | linux-v1-cpu-paymentservice-r02 | cpu_saturation | paymentservice | r02 | 206-40 | fault_active_no_impact |
| 51 | linux-v1-cpu-checkoutservice-r03 | cpu_saturation | checkoutservice | r03 | 206-40 | fault_active_no_impact |
| 52 | linux-v1-loss-checkout-payment-r03 | packet_loss | checkoutservice→paymentservice | r03 | 206-40 | fault_active_no_impact |
| 62 | linux-v1-surge-l1-r02 | traffic_surge | frontend 진입 부하 L1 | r02 | 206-40 | fault_active_no_impact |
| 63 | linux-v1-cpu-checkoutservice-r01 | cpu_saturation | checkoutservice | r01 | 206-40 | fault_active_no_impact |

셀(같은 fault·원인) 기준:

| fault | 원인 | 무영향 / 셀 반복 수 |
|---|---|---|
| cpu_saturation | checkoutservice | 3 / 3 |
| cpu_saturation | paymentservice | 3 / 3 |
| network_delay | checkoutservice→paymentservice | 1 / 3 |
| packet_loss | checkoutservice→paymentservice | 3 / 3 |
| pod_failure | recommendationservice | 2 / 3 |
| traffic_surge | frontend 진입 부하 L1 | 3 / 3 |

무영향은 cpu checkout·payment, loss checkout→payment, surge L1에서 셀 전체(3/3)였다. 원인은 분석하지 않았다(추정: CPU limit 안에서 처리, 결제 호출량이 적음, L1 4.8 tx/s < 용량 C 6 tx/s). 판정 기준(evaluation_policy v3)은 바꾸지 않았다.

참고: #2 `linux-v1-delay-checkout-payment-r02`(206-39)는 206-39.md pair 기록에 impact 언급이 없지만 incident는 `confirmed: false`, `fault_active_no_impact`다. 이 표는 incident 값을 따른다.

## 실패한 시도 (3, 모두 인프라 원인·재시도로 대체)

| # | pair_id | 실패 시도 | 수집 PC | 사유 | 대체 | run 폴더 |
|---|---|---|---|---|---|---|
| 20 | linux-v1-pod-productcatalogservice-r01 | 1 | 206-40 | control run raw export incomplete(spanmetrics_duration_bucket 1점, OTel gateway scrape up=0). 이후 생긴 누락 허용 기준(7.20)으로는 허용될 수준이지만 시도 1은 엄격 판정 유지 | 시도 2 valid | `linux-v1-control-pod-productcatalogservice-r01` 1개(fault run 시작 안 함) |
| 32 | linux-v1-cpu-currencyservice-r02 | 1 | 206-40 | fault run 후처리 중 감시 loop 15.1 s 정지(>15 s 규칙), 메모리 압박·oomd 터미널 kill(7.21) | 시도 2 valid | `linux-v1-cpu-currencyservice-r02` 1개(control 시작 안 함) |
| 38 | linux-v1-pod-currencyservice-r02 | 1 | 206-39 | control run 부하 중 호스트 절전 46 h 18 m → `Workload console inactive >60s`(7.22) | 시도 2 valid(206-40) | 206-39에 2개(fault valid, control 실패). audit만 206-40에 복사 |

기록 단계만 실패했던 #15 `linux-v1-surge-l3-r01`은 수집이 valid라 재수집하지 않았다(`resolved_pairs`, 시도 1 채택).

## 69 pair 표

`#`은 schedule 번호. 채택 시도가 1이면 run ID는 pair_id(fault)와 `linux-v1-control-…`(control), 2이면 `-a2`가 붙는다.

| # | pair_id | fault | 원인(서비스/연결) | 반복 | 수집 PC (environment_id) | shard | 채택 시도 (run ID) | valid | impact | status | 실패한 이전 시도와 사유 · 비고 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | linux-v1-cpu-productcatalogservice-r01 | cpu_saturation | productcatalogservice | r01 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 2 | linux-v1-delay-checkout-payment-r02 | network_delay | checkoutservice→paymentservice | r02 | 206-39 | 206-39 | 1 | true | **없음** | fault_active_no_impact | – |
| 3 | linux-v1-surge-l2-r01 | traffic_surge | frontend 진입 부하 L2 | r01 | 206-39 | 206-39 | 1 | true | 있음 (latency_increase) | abnormal_impacted | 회복 관측 fail(stable_at 없음) → status abnormal_impacted. valid |
| 4 | linux-v1-pod-checkoutservice-r02 | pod_failure | checkoutservice | r02 | 206-40 | 206-40 | 1 | true | 있음 (error_rate_increase) | recovered | – |
| 5 | linux-v1-loss-front-currency-r02 | packet_loss | frontend→currencyservice | r02 | 206-39 | 206-39 | 1 | true | 있음 (latency_increase) | recovered | – |
| 6 | linux-v1-delay-front-recommendation-r02 | network_delay | frontend→recommendationservice | r02 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 7 | linux-v1-pod-recommendationservice-r01 | pod_failure | recommendationservice | r01 | 206-39 | 206-39 | 1 | true | **없음** | fault_active_no_impact | – |
| 8 | linux-v1-delay-front-currency-r02 | network_delay | frontend→currencyservice | r02 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 9 | linux-v1-cpu-paymentservice-r01 | cpu_saturation | paymentservice | r01 | 206-39 | 206-39 | 1 | true | **없음** | fault_active_no_impact | – |
| 10 | linux-v1-delay-checkout-payment-r01 | network_delay | checkoutservice→paymentservice | r01 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 11 | linux-v1-delay-recommendation-product-r01 | network_delay | recommendationservice→productcatalogservice | r01 | 206-39 | 206-39 | 1 | true | 있음 (latency_increase) | recovered | – |
| 12 | linux-v1-pod-recommendationservice-r03 | pod_failure | recommendationservice | r03 | 206-40 | 206-40 | 1 | true | **없음** | fault_active_no_impact | – |
| 13 | linux-v1-delay-front-currency-r03 | network_delay | frontend→currencyservice | r03 | 206-39 | 206-39 | 1 | true | 있음 (latency_increase) | recovered | – |
| 14 | linux-v1-delay-front-product-r02 | network_delay | frontend→productcatalogservice | r02 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 15 | linux-v1-surge-l3-r01 | traffic_surge | frontend 진입 부하 L3 | r01 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | 시도 1 채택. 수집 valid, incident-record 단계만 실패 → 10/26 기록 단계 수동 재실행(`resolved_pairs`, status.json은 failed 그대로) |
| 16 | linux-v1-pod-paymentservice-r03 | pod_failure | paymentservice | r03 | 206-39 | 206-39 | 1 | true | 있음 (error_rate_increase) | recovered | – |
| 17 | linux-v1-pod-currencyservice-r03 | pod_failure | currencyservice | r03 | 206-39 | 206-39 | 1 | true | 있음 (error_rate_increase) | recovered | – |
| 18 | linux-v1-delay-front-product-r01 | network_delay | frontend→productcatalogservice | r01 | 206-39 | 206-39 | 1 | true | 있음 (latency_increase) | recovered | – |
| 19 | linux-v1-loss-recommendation-product-r01 | packet_loss | recommendationservice→productcatalogservice | r01 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 20 | linux-v1-pod-productcatalogservice-r01 | pod_failure | productcatalogservice | r01 | 206-40 | 206-40 | 2 (`linux-v1-pod-productcatalogservice-r01-a2`) | true | 있음 (error_rate_increase) | recovered | 시도 1 `linux-v1-pod-productcatalogservice-r01`(206-40): control run(첫 run) raw export incomplete — spanmetrics_duration_bucket 1점 누락(OTel gateway scrape up=0). fault run 시작 안 함 |
| 21 | linux-v1-cpu-productcatalogservice-r02 | cpu_saturation | productcatalogservice | r02 | 206-39 | 206-39 | 1 | true | 있음 (latency_increase) | recovered | – |
| 22 | linux-v1-pod-checkoutservice-r03 | pod_failure | checkoutservice | r03 | 206-39 | 206-39 | 1 | true | 있음 (error_rate_increase) | recovered | – |
| 23 | linux-v1-cpu-paymentservice-r03 | cpu_saturation | paymentservice | r03 | 206-40 | 206-40 | 1 | true | **없음** | fault_active_no_impact | – |
| 24 | linux-v1-pod-checkoutservice-r01 | pod_failure | checkoutservice | r01 | 206-40 | 206-40 | 1 | true | 있음 (error_rate_increase) | recovered | – |
| 25 | linux-v1-cpu-checkoutservice-r02 | cpu_saturation | checkoutservice | r02 | 206-40 | 206-40 | 1 | true | **없음** | fault_active_no_impact | – |
| 26 | linux-v1-loss-checkout-payment-r02 | packet_loss | checkoutservice→paymentservice | r02 | 206-39 | 206-39 | 1 | true | **없음** | fault_active_no_impact | – |
| 27 | linux-v1-delay-front-recommendation-r01 | network_delay | frontend→recommendationservice | r01 | 206-39 | 206-39 | 1 | true | 있음 (latency_increase) | recovered | – |
| 28 | linux-v1-delay-checkout-payment-r03 | network_delay | checkoutservice→paymentservice | r03 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 29 | linux-v1-pod-paymentservice-r02 | pod_failure | paymentservice | r02 | 206-40 | 206-40 | 1 | true | 있음 (error_rate_increase) | recovered | – |
| 30 | linux-v1-cpu-recommendationservice-r01 | cpu_saturation | recommendationservice | r01 | 206-39 | 206-39 | 1 | true | 있음 (latency_increase) | recovered | – |
| 31 | linux-v1-delay-front-product-r03 | network_delay | frontend→productcatalogservice | r03 | 206-39 | 206-39 | 1 | true | 있음 (latency_increase) | recovered | – |
| 32 | linux-v1-cpu-currencyservice-r02 | cpu_saturation | currencyservice | r02 | 206-40 | 206-40 | 2 (`linux-v1-cpu-currencyservice-r02-a2`) | true | 있음 (latency_increase) | recovered | 시도 1 `linux-v1-cpu-currencyservice-r02`(206-40): fault run 후처리 중 감시 loop 15.1 s 정지(observation gap >15 s), 직후 systemd-oomd가 터미널 scope kill. control run 시작 안 함 |
| 33 | linux-v1-loss-front-product-r03 | packet_loss | frontend→productcatalogservice | r03 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 34 | linux-v1-pod-currencyservice-r01 | pod_failure | currencyservice | r01 | 206-40 | 206-40 | 1 | true | 있음 (error_rate_increase) | recovered | – |
| 35 | linux-v1-loss-front-product-r02 | packet_loss | frontend→productcatalogservice | r02 | 206-39 | 206-39 | 1 | true | 있음 (latency_increase) | recovered | – |
| 36 | linux-v1-surge-l1-r03 | traffic_surge | frontend 진입 부하 L1 | r03 | 206-39 | 206-39 | 1 | true | **없음** | fault_active_no_impact | – |
| 37 | linux-v1-loss-checkout-payment-r01 | packet_loss | checkoutservice→paymentservice | r01 | 206-40 | 206-40 | 1 | true | **없음** | fault_active_no_impact | – |
| 38 | linux-v1-pod-currencyservice-r02 | pod_failure | currencyservice | r02 | 206-40 | 206-40-c(#38 재시도) | 2 (`linux-v1-pod-currencyservice-r02-a2`) | true | 있음 (error_rate_increase) | recovered | 시도 1 `linux-v1-pod-currencyservice-r02`(206-39): fault run valid, control run 부하 중 호스트 절전 46 h 18 m → `Workload console inactive >60s`로 실패 |
| 39 | linux-v1-delay-front-recommendation-r03 | network_delay | frontend→recommendationservice | r03 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 40 | linux-v1-loss-front-recommendation-r02 | packet_loss | frontend→recommendationservice | r02 | 206-40 | 206-40-b(이관) | 1 | true | 있음 (latency_increase) | recovered | – |
| 41 | linux-v1-surge-l1-r01 | traffic_surge | frontend 진입 부하 L1 | r01 | 206-40 | 206-40 | 1 | true | **없음** | fault_active_no_impact | – |
| 42 | linux-v1-surge-l3-r02 | traffic_surge | frontend 진입 부하 L3 | r02 | 206-40 | 206-40-b(이관) | 1 | true | 있음 (latency_increase) | recovered | – |
| 43 | linux-v1-delay-front-currency-r01 | network_delay | frontend→currencyservice | r01 | 206-40 | 206-40-b(이관) | 1 | true | 있음 (latency_increase) | recovered | – |
| 44 | linux-v1-delay-recommendation-product-r03 | network_delay | recommendationservice→productcatalogservice | r03 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 45 | linux-v1-loss-recommendation-product-r03 | packet_loss | recommendationservice→productcatalogservice | r03 | 206-40 | 206-40-b(이관) | 1 | true | 있음 (latency_increase) | recovered | – |
| 46 | linux-v1-loss-front-recommendation-r01 | packet_loss | frontend→recommendationservice | r01 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 47 | linux-v1-cpu-paymentservice-r02 | cpu_saturation | paymentservice | r02 | 206-40 | 206-40-b(이관) | 1 | true | **없음** | fault_active_no_impact | – |
| 48 | linux-v1-cpu-productcatalogservice-r03 | cpu_saturation | productcatalogservice | r03 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 49 | linux-v1-cpu-currencyservice-r01 | cpu_saturation | currencyservice | r01 | 206-40 | 206-40-b(이관) | 1 | true | 있음 (latency_increase) | recovered | – |
| 50 | linux-v1-surge-l3-r03 | traffic_surge | frontend 진입 부하 L3 | r03 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 51 | linux-v1-cpu-checkoutservice-r03 | cpu_saturation | checkoutservice | r03 | 206-40 | 206-40-b(이관) | 1 | true | **없음** | fault_active_no_impact | – |
| 52 | linux-v1-loss-checkout-payment-r03 | packet_loss | checkoutservice→paymentservice | r03 | 206-40 | 206-40 | 1 | true | **없음** | fault_active_no_impact | – |
| 53 | linux-v1-pod-productcatalogservice-r02 | pod_failure | productcatalogservice | r02 | 206-40 | 206-40-b(이관) | 1 | true | 있음 (error_rate_increase) | recovered | – |
| 54 | linux-v1-cpu-currencyservice-r03 | cpu_saturation | currencyservice | r03 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 55 | linux-v1-surge-l2-r03 | traffic_surge | frontend 진입 부하 L2 | r03 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 56 | linux-v1-pod-recommendationservice-r02 | pod_failure | recommendationservice | r02 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 57 | linux-v1-cpu-recommendationservice-r03 | cpu_saturation | recommendationservice | r03 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 58 | linux-v1-loss-front-recommendation-r03 | packet_loss | frontend→recommendationservice | r03 | 206-40 | 206-40-b(이관) | 1 | true | 있음 (latency_increase) | recovered | – |
| 59 | linux-v1-loss-front-currency-r03 | packet_loss | frontend→currencyservice | r03 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 60 | linux-v1-pod-paymentservice-r01 | pod_failure | paymentservice | r01 | 206-40 | 206-40-b(이관) | 1 | true | 있음 (error_rate_increase) | recovered | – |
| 61 | linux-v1-loss-recommendation-product-r02 | packet_loss | recommendationservice→productcatalogservice | r02 | 206-40 | 206-40-b(이관) | 1 | true | 있음 (latency_increase) | recovered | – |
| 62 | linux-v1-surge-l1-r02 | traffic_surge | frontend 진입 부하 L1 | r02 | 206-40 | 206-40-b(이관) | 1 | true | **없음** | fault_active_no_impact | – |
| 63 | linux-v1-cpu-checkoutservice-r01 | cpu_saturation | checkoutservice | r01 | 206-40 | 206-40-b(이관) | 1 | true | **없음** | fault_active_no_impact | – |
| 64 | linux-v1-cpu-recommendationservice-r02 | cpu_saturation | recommendationservice | r02 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 65 | linux-v1-loss-front-currency-r01 | packet_loss | frontend→currencyservice | r01 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 66 | linux-v1-pod-productcatalogservice-r03 | pod_failure | productcatalogservice | r03 | 206-40 | 206-40-b(이관) | 1 | true | 있음 (error_rate_increase) | recovered | – |
| 67 | linux-v1-delay-recommendation-product-r02 | network_delay | recommendationservice→productcatalogservice | r02 | 206-40 | 206-40-b(이관) | 1 | true | 있음 (latency_increase) | recovered | – |
| 68 | linux-v1-loss-front-product-r01 | packet_loss | frontend→productcatalogservice | r01 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |
| 69 | linux-v1-surge-l2-r02 | traffic_surge | frontend 진입 부하 L2 | r02 | 206-40 | 206-40 | 1 | true | 있음 (latency_increase) | recovered | – |

## 데이터 위치

| PC | 폴더 | linux-v1 run 폴더 | 기준 |
|---|---|---|---|
| 206-40 | `/home/cloudman/Documents/sentrix-final-v1-main/runs/` | 104 = 51 pair × 2 + 실패 시도 2(#20·#32 시도 1) | 11/03 |
| 206-39 | 206-39 저장소 `runs/` | 38 = 18 pair × 2 + #38 시도 1의 2 | 10/30 (206-39.md) |

206-39 데이터를 206-40으로 모으는 계획은 SETUP-REVIEW 7.23(제안, 미실행).
