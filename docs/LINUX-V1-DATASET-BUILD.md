# linux-v1 데이터셋 빌드 기록 (linux-v1-v0)

기준일: 2026-11-23 · branch `dataset-linux-v1` · 생성기 `features/build_linux_v1.py`, 어댑터 `features/adapters/linux_v1.py`
규칙: `docs/LINUX-V1-DATA-TRANSLATION.md`(변경 기록 포함), 고정 방법 `docs/METHOD-FREEZE-v2.md`(399d3d0).
**이 점검에서는 개수·결측 비율·형식만 봤다. feature 값 분포·점수·순위는 보지 않았다.**

## 1. 실행

| 항목 | 값 |
|---|---|
| 명령 | `.venv/bin/python -m features.build_linux_v1 --out data/features/linux-v1-v0` (worktree `/home/cloudman/Documents/wt-dataset`) |
| 실행 방식 | `systemd-run --user --unit=lv1-build`(터미널 scope와 별도 cgroup, SETUP-REVIEW 7.21 oomd 이력), 메모리 기록 `lv1-memlog`(1분 간격) |
| 시각 | 2026-11-23 14:50:15 ~ 14:57:06 KST, **411 s**, 중단·resume 없음 |
| 코드 | commit `f179180ef0793752132ffc56b2d1f67cefa5a903`, `features/` dirty = false |
| 코드 sha256 | compute.py `1661a9f1dcc7…cb34`(고정값 일치), windows.py `1e4450d9…8393`, schema.py `4d39c885…4c28234`, adapters/linux_v1.py `b09b5fb8…5208` |
| 입력 | dataset-roots.yaml: 206-40 = `/home/cloudman/Documents/sentrix-final-v1-main`(51 pair), 206-39 = `/home/cloudman/sentrix-data/206-39`(18 pair). schedule.csv sha256 `83fce587…59cf`. 입력 parquet 414개(138 run × 3) sha256을 각 run `pipeline-v2.json` 해시와 대조, 모두 일치 |
| 검사 4종 | run ID 충돌 없음 · pair당 채택 시도 1 · 채택 69 = schedule 69 · compute.py 해시 일치 |
| 제외 시도 | #20·#32·#38 시도 1 (사유는 build-summary `excluded_attempts`, decisions.yaml에서) |
| 메모리 | worker 최대 RSS 1,762 MB(case당 1.1~1.8 GB), 빌드 cgroup 최대 4.8 GB(page cache 포함), 호스트 available 최저 7.0 GB, swap 41 MB, PSI some avg60 최대 0.90 |
| 경고 | `RuntimeWarning: All-NaN slice` 1,656건(compute.py `nanmax`; rx/tx 등 전부 NaN인 열). 오류 0 |

## 2. 산출물 (git에 올리지 않음)

위치: `/home/cloudman/Documents/wt-dataset/data/features/linux-v1-v0/` (폴더 전체 43 MB, 그중 `_parts/` case별 중간 파일)

| 파일 | 바이트 | sha256 |
|---|---|---|
| cases.parquet | 46,133 | `fe18268db6340bad49efe2be5eba3dbadc9ec7fb2b77d8c9c6217bcafb9fe2e5` |
| ranking.parquet | 1,015,201 | `34c4c4f8876eea9abbef6d34e39d80f158dc40cda853c8683e72caaf7dc39ec6` |
| ranking-nodeview.parquet | 1,554,725 | `8f435d9f6e4a4749fdfb95f7b543986e358af9a612d0b660904f791234521486` |
| detection.parquet | 3,499,944 | `c25c0b35bbbb11863c55e86e9535a9b719512edb1942d921a333fd9b6834be1a` |
| detection-ineligible.parquet | 133,752 | `211a3baa80aefb82303dac58d488cd600a3b5ab7f125bcbfdc5995d6d9652fee` |
| edges.parquet | 1,661,510 | `d82c1993acd489cf46815bca285206708f9857ebcd78433b7751ea54f913cafd` |
| folds.json | 6,827 | `3b5226c20a1d47cb0cf8218eedaf8ca487baeac2e061d85ae81dfdd88dd385db` |
| build-summary.json | 8,377 | `cde1c99f8a819f2b755c9b6f4f928e65958a18087ac9ae71b45c5387b5cc9cbb` |
| build-progress.log | 14,771 | `8ab854d67ccaa3be379c93df7185981c09f267a858ed9e0463c23d0f69320ba2` |

메모리 기록·stdout: `data/features/linux-v1-v0-memory.tsv`, `data/features/linux-v1-v0-stdout.log`.

## 3. case

| 구분 | fold 1 | fold 2 | fold 3 | 합계 |
|---|---|---|---|---|
| 장애 run | 23 | 23 | 23 | 69 |
| 대조 run | 23 | 23 | 23 | 69 |
| 합계 | 46 | 46 | 46 | **138** |

| 장애 | run (fold당 수) | 적격 | onset_source |
|---|---|---|---|
| cpu_saturation | 15 (5/5/5) | 9 | started_at 15 |
| network_delay | 15 (5/5/5) | 14 | started_at 15 |
| packet_loss | 15 (5/5/5) | 12 | started_at 15 |
| pod_failure | 15 (5/5/5) | 13 | **ready_zero 15, 대체 규칙 0** |
| traffic_surge | 9 (3/3/3) | 6 | started_at 9 |
| 합계 | 69 | **54** | 대조 69는 sham_of_fault |

- Pod onset − started_at: 4.1 ~ 14.9 s (15개 모두 장애 구간 안에서 Ready=0 관측).
- 같은 pair의 장애·대조 run은 모두 같은 fold. 허용 누락점 0. recovery 없음 2 run(#3 `surge-l2-r01`과 그 대조, 알려진 회복 관측 fail).

## 4. 표 행 수

| 표 | 행 | 내용 |
|---|---|---|
| ranking | 5,038 | 적격 CPU 9 + Pod 13 = 22 case(CPU 2,101, Pod 2,937), window마다 후보 11행·정답 1개 |
| ranking-nodeview | 7,458 | 적격 지연 14·손실 12·급증 6 = 32 case, 정답 0 |
| detection | 12,473 | 양성 1,136(적격 fault_active) / 음성 11,337(recovered 8,645, sham_active 1,452, normal 1,240). **f_ 열 58개** |
| detection-ineligible | 316 | 비적격 15 case의 fault_active (meta_eligible false) |
| edges | 170,136 | 138 case, 방향 연결 8개, 모든 label의 window |

- 검산: sham_active 1,452 = 적격 fault_active 1,136 + 비적격 316.
- edges의 연결 8개: checkout→email, checkout→payment, checkout→productcatalog, frontend→checkout, frontend→currency, frontend→productcatalog, frontend→recommendation, recommendation→productcatalog. **정답 연결 5개 모두 포함**, 지연·손실 30 case(장애+대조 60 run) 모두 정답 연결의 baseline_stats 행이 있다.

## 5. 결측 비율

ranking(적격 CPU·Pod의 fault_active) 기준, rel18 × 후보 11:

| feature | adservice | cartservice | checkout | currency | email | frontend | payment | productcatalog | recommendation | redis-cart | shipping |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cpu_cores dmean/dmax | 0 | 0 | 0.031 | 0.026 | 0 | 0 | 0.028 | 0.028 | 0.044 | 0 | 0 |
| cpu_limit_ratio dmean/dmax | 0 | 0 | 0.068 | 0.066 | 0 | 0 | 0.066 | 0.074 | 0.044 | 0 | 0 |
| mem_limit_ratio dmean/dmax | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **net_rx/tx_pkts dmean/dmax (4개)** | **1** | **1** | **1** | **1** | **1** | **1** | **1** | **1** | **1** | **1** | **1** |
| net_drop_pkts dmean/dmax | 0 | 0 | 0.002 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ct_in_rate_lr | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| ct_in_err_d, in_p50_lr, in_p90_lr | 1 | 1 | 0.138 | 0.133 | 0.402 | 0 | 0.402 | 0.138 | 0.177 | 1 | 1 |
| ct_out_p90_lr | 1 | 1 | 0.138 | 1 | 1 | 0 | 1 | 1 | 0.314 | 1 | 1 |
| ct_in_edge_p90_lr | 1 | 1 | 0.138 | 0.133 | 0.402 | 1 | 0.402 | 0.138 | 0.177 | 1 | 1 |

- rx/tx 4개는 전부 NaN(번역 결정 1절대로). 탐지 표에서도 해당 8열(`__max/__mean`)만 100% NaN.
- trace feature 100% NaN: adservice·cartservice·redis-cart·shippingservice(trace 미계측 서비스), frontend의 in_edge(계측된 호출자 없음), out_p90은 호출하는 계측 서비스가 없는 노드.
- CPU 계열의 2.6~7.4% 결측은 Pod 장애 대상의 컨테이너 지표 중단(NaN 유지 규칙).
- 로그 feature 결측(ranking+nodeview): **productcatalogservice 94.5%**(로그 거의 없음, 번역 결정 5절), currencyservice 1.9%, 나머지 0. redis-cart는 결측 0(로그 개수 0도 값으로 들어감).
- 탐지 표 결측: rx/tx 8열 100%, trace 집계 3.1~3.3%, 나머지 0.

## 6. case별 label window 수

| label | 최소 | 중앙 | 최대 |
|---|---|---|---|
| baseline_stats | 10 | 28 | 41 |
| normal | 8 | 9 | 10 |
| transition | 8 | 9 | 10 |
| fault_active / sham_active | 20 | 21 | 22 |
| recovering | 2 | 3 | 71 |
| recovered | 35 | 63 | 81 |
| excluded | 21 | 21 | 22 |

## 7. 눈여겨볼 것 (목록)

- **baseline_stats window 10개 미만인 case: 0.** 10~11개인 case는 22개(11 pair, 장애·대조 쌍)로 모두 schedule onset 420~440 s pair다(warmup 180 + normal 120을 빼면 설계상 10개). `delay-front-currency-r02`, `delay-checkout-payment-r01`, `pod-recommendationservice-r03`, `pod-currencyservice-r01`, `loss-front-recommendation-r02`, `surge-l3-r02`, `loss-recommendation-product-r03`, `cpu-currencyservice-r01`, `pod-productcatalogservice-r02`, `pod-paymentservice-r01`, `delay-recommendation-product-r02`.
- **Pod onset 대체 규칙 사용: 0.**
- recovering이 긴 case: `surge-l2-r01`(#3) 장애·대조 71개(stable_at 없음 → 끝까지 recovering, 알려진 사항). Pod 장애 8 pair는 13~19개(회복 확인까지 시간 걸림), `cpu-paymentservice-r03` 13개. 나머지는 2~3개.
- 허용 누락점(`tolerated_missing_points_unix`) 0.
- 로그 오류 판정 등 구현 세부는 번역 결정 변경 기록(2026-11-23)에 있다.
