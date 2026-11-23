# linux-v1 평가 결과

방법: `docs/METHOD-FREEZE-v2.md`(고정 커밋 399d3d0) 4절, 데이터 번역 `docs/LINUX-V1-DATA-TRANSLATION.md`, 데이터셋 `docs/LINUX-V1-DATASET-BUILD.md`(linux-v1-v0).
평가 코드 `evaluation/run_linux_v1.py`(f97ec54). **결과를 보고 방법을 바꾸지 않는다.**

| 구분 | 상태 |
|---|---|
| **B 방식 (주 결과)** | 보류. RE2-OB 특징 표를 다시 만들었더니 sha256이 frozen.json과 달라서(1절), 재현 확인(3절) 결과를 보고 사용자가 정한다 |
| A 방식 (보조) | 2026-11-23 실행, 2절 |
| rel14 (보조) | B 방식과 함께 계산할 예정 |

## 1. RE2-OB 특징 표 재생성과 해시 (2026-11-23)

- 입력: Zenodo 14590730 `RE2-OB.zip`. sha256 `0605a36c…7513`, md5 `b9e23f88…de4`로 RE2OB-INVENTORY와 일치. case 90개, 파일 구성도 같음.
- 명령: `python -m features.build_re2ob --root data/RE2/RE2-OB --out data/features/re2ob-v0 --workers 2`. 코드 f97ec54이고, 272e514 이후 compute·re2ob 어댑터·build_re2ob는 바뀌지 않았다. 패키지 버전은 원래 기록과 같다. Linux, Python 3.12.3.

| 파일 | 원래 (frozen.json, features-v0 `output-sha256.txt`) | 재생성 | 결과 |
|---|---|---|---|
| ranking.parquet | `c7dfdc76…e5c9` | `138efc76…65f8` | 다름 (행 61,336·f_ 열 67·양성 5,576은 같음) |
| detection.parquet | `c9b9ca43…4ffe` | `f41ae001…459e` | 다름 (행 9,176·f_ 열 58·양성 5,576은 같음) |
| cases.parquet | `a3c3b9c5…81a0` | 같음 | 일치 |
| edges.parquet | `5a7198e7…b40f` | 같음 | 일치 |
| folds.json | `650568b8…9641` | `8880dd9c…9ab8` | **형식 차이**: 재생성본의 줄바꿈을 CRLF로 바꾸면 sha256이 `650568b8…9641`로 원래와 같다. fold별 case ID 집합도 R6 기록(`experiments/20261027-re2ob-r6-models/parts/rf.json`의 case 90개 fold)과 같다 |

- 원래 표는 Windows에서 만들었다(`training/freeze_v2.py` 사용 예의 `.venv-r6/Scripts/python`, CRLF folds.json).
- 해석(확인 안 됨): 정수·분위수만 쓰는 cases·edges는 같고, 실수 평균·회귀가 들어가는 ranking·detection만 다르다. 운영체제·컴파일러·BLAS 차이로 인한 부동소수점 끝자리 차이로 보인다. 원래 표가 없어 값끼리 비교하지는 못했다.

## 2. A 방식 (보조) — RE2-OB 최종 모델을 그대로 적용

- 실행: `python -m evaluation.run_linux_v1 --features data/features/linux-v1-v0 --out experiments/20261123-linux-v1-eval-a` (2026-11-23, 23초). 결과 파일: `experiments/20261123-linux-v1-eval-a/results.json`, `results.md`.
- 고정 모델 파일 4개(v2 RF·LightGBM, v1 LambdaRank·탐지기)의 sha256이 각 frozen.json과 같음을 확인했다.
- A 방식은 RE2-OB 특징 표를 쓰지 않는다. 운영 문턱(학습 정상 window 점수의 95번째 백분위)이 RE2-OB 표에 있어야 정해지므로 **run 경보율은 A 방식에서 나오지 않는다**(B 방식에서 계산).

### 2.1 원인 서비스 순위 (적격 CPU 9 + Pod 13 = 22 case)

| 방법 | n | AC@1 (95% CI) | AC@3 (95% CI) | Avg@5 (95% CI) | MRR (95% CI) |
|---|---:|---|---|---|---|
| **RF rel18 (v2 주 방법)** | 22 | 0.500 (0.318–0.682) | 0.909 (0.773–1.000) | **0.827 (0.745–0.900)** | 0.697 (0.568–0.818) |
| V4 (v1 방법) | 22 | 0.727 (0.545–0.886) | 1.000 (1.000–1.000) | 0.941 (0.900–0.977) | 0.860 (0.765–0.943) |
| stat_combined | 22 | 0.500 (0.318–0.682) | 0.818 (0.636–0.955) | 0.782 (0.673–0.877) | 0.672 (0.542–0.803) |
| random | 22 | 0.091 | 0.273 | 0.273 | 0.275 |

장애 종류별 (n / AC@1 / AC@3 / Avg@5 / MRR):

| 방법 | CPU 포화 (n=9) | Pod 장애 (n=13) | paymentservice 원인 (n=3) |
|---|---|---|---|
| RF rel18 | 1.000 / 1.000 / 1.000 / 1.000 | 0.154 / 0.846 / 0.708 / 0.487 | 0.333 / 0.667 / 0.667 / 0.528 |
| V4 | 1.000 / 1.000 / 1.000 / 1.000 | 0.538 / 1.000 / 0.900 / 0.763 | 0.833 / 1.000 / 0.967 / 0.917 |
| stat_combined | 0.778 / 1.000 / 0.956 / 0.889 | 0.308 / 0.692 / 0.662 / 0.522 | 0.667 / 1.000 / 0.867 / 0.778 |
| random | 0.091 / 0.273 / 0.273 / 0.275 | 같음 | 같음 |

paymentservice 원인 3 case는 모두 Pod 장애다(CPU 3 case는 impact가 없어 비적격).

짝지은 비교 (case bootstrap 2000, Avg@5 차이):

| 비교 | 차이 | 95% CI | 판정 |
|---|---:|---|---|
| RF rel18 − stat_combined | +0.045 | −0.036 ~ 0.127 | 차이 없음 |
| RF rel18 − V4 | −0.114 | −0.186 ~ −0.045 | **나쁨** |
| V4 − stat_combined | +0.159 | 0.091 ~ 0.232 | 나음 |

정답 순위가 4위 이하인 case:

| 방법 | case | 장애 | 원인 | 순위 |
|---|---|---|---|---:|
| RF rel18 | pod-checkoutservice-r03 | pod_failure | checkoutservice | 4 |
| RF rel18 | pod-paymentservice-r02 | pod_failure | paymentservice | 4 |
| stat_combined | pod-checkoutservice-r02 | pod_failure | checkoutservice | 4 |
| stat_combined | pod-checkoutservice-r03 | pod_failure | checkoutservice | 5 |
| stat_combined | pod-currencyservice-r02-a2 | pod_failure | currencyservice | 4 |
| stat_combined | pod-currencyservice-r03 | pod_failure | currencyservice | 4 |
| V4 | 없음 | | | |

### 2.2 장애 탐지 (window, detection.parquet 12,473개, 양성 비율 0.091)

| 방법 | AUROC (95% CI) | AUPRC |
|---|---|---:|
| **LightGBM 집계 58개 (v2 주 방법)** | **0.873 (0.829–0.917)** | 0.659 |
| v1 탐지기 (rel 집계 36개) | 0.774 (0.699–0.843) | 0.599 |
| stat_metric | 0.715 (0.638–0.789) | 0.369 |

- 비적격 장애 run의 fault_active window 316개는 AUROC에서 뺐다(detection-ineligible.parquet).

### 2.3 호출 경로 순위 (적격 지연 14 + 손실 12 = 26 case, 후보 연결 수 중앙값 8)

| 방법 | n | AC@1 (95% CI) | AC@3 (95% CI) | Avg@5 (95% CI) | MRR |
|---|---:|---|---|---|---:|
| 통계 연결 점수 | 26 | 0.615 (0.423–0.808) | 0.692 (0.500–0.846) | 0.700 (0.538–0.854) | 0.699 |
| random | 26 | 0.125 | 0.375 | 0.375 | 0.340 |

| 구분 | n | AC@1 | AC@3 | Avg@5 |
|---|---:|---:|---:|---:|
| 연결 지연 | 14 | 1.000 | 1.000 | 1.000 |
| 패킷 손실 | 12 | 0.167 | 0.333 | 0.350 |
| checkoutservice→paymentservice | 2 | 1.000 | 1.000 | 1.000 |
| frontend→currencyservice | 6 | 0.500 | 0.500 | 0.500 |
| frontend→productcatalogservice | 6 | 0.833 | 1.000 | 0.967 |
| frontend→recommendationservice | 6 | 0.500 | 0.500 | 0.567 |
| recommendationservice→productcatalogservice | 6 | 0.500 | 0.667 | 0.667 |

정답 연결 순위가 4위 이하인 case(모두 패킷 손실): loss-front-currency-r01·r02·r03 (8위), loss-front-recommendation-r01·r03 (5위)·r02 (6위), loss-recommendation-product-r01 (4위)·r03 (7위).

### 2.4 노드 보기 (연결 장애 26 case, RF rel18 서비스 순위)

| 기준 | AC@1 | AC@3 | AC@5 |
|---|---:|---:|---:|
| 양 끝 중 하나 | 0.385 | 0.885 | 0.923 |
| 출발 서비스 | 0.077 | 0.462 | 0.846 |
| 도착 서비스 | 0.308 | 0.692 | 0.813 |

### 2.5 트래픽 급증: frontend 순위 (적격 6 case, 서술)

| case | frontend 순위 |
|---|---:|
| surge-l2-r01 | 2 |
| surge-l2-r02 | 6 |
| surge-l2-r03 | 6 |
| surge-l3-r01 | 6 |
| surge-l3-r02 | 7 |
| surge-l3-r03 | 6 |

### 2.6 해석 (사실과 구분)

- A 방식에서 RF rel18은 V4보다 짝지은 비교로 나빴다(−0.114). 차이는 Pod 장애에서 나왔고(Avg@5 0.708 vs 0.900), CPU 포화에서는 둘 다 1.000이다. Pod 장애는 RE2-OB에 없는 장애이고, METHOD-FREEZE-v2 5절에 "pod_failure와 NaN → 0" 위험으로 미리 적혀 있다. 이 결과로 주 방법을 바꾸지 않는다.
- 탐지 AUROC는 RE2-OB(0.996)보다 낮다(0.873). 번역 결정 5절의 위험(rx/tx 결측, 회복 직후 CPU rate 꼬리가 recovered 음성에 들어감)과 관련이 있을 수 있으나 확인하지 않았다.
- 패킷 손실 2%에서 통계 연결 점수가 약했다(Avg@5 0.350). METHOD-FREEZE-v2 4.1절의 알려진 위험("2% 손실은 신호가 약할 수 있다")과 같은 방향이다.
- 노드 보기 'either'는 느슨한 기준이며 논문 정의가 아니다(코드 주석).

## 3. RE2-OB 재현 확인 — 합격 기준 (결과 보기 전, 2026-11-23)

목적: 다시 만든 RE2-OB 표(1절)가 고정 때 쓴 표와 결과상 같은지 확인한다. linux-v1 데이터는 쓰지 않는다.

- 절차: 다시 만든 `data/features/re2ob-v0`로 `training/freeze_v2.py`를 그대로 실행한다. 출력은 새 폴더 `experiments/20261123-re2ob-v2-rebuild-check`이고, 기존 freeze 폴더는 덮어쓰지 않는다.
- **합격 = (a)와 (b)를 모두 만족**
  - (a) 고른 하이퍼파라미터가 frozen.json과 같다. RF: min_samples_leaf 100, max_features 0.5. LightGBM: num_leaves 15, n_estimators 300, min_child_samples 20.
  - (b) 내부 LOSO Avg@5(frozen 0.9622222)와 내부 반복 CV AUROC(frozen 0.9960397)가 소수 셋째 자리까지 같다. 두 값 모두 소수 셋째 자리에서 반올림해 비교한다(0.962, 0.996).
- 모델 파일 sha256은 부동소수점 차이로도 달라질 수 있으므로 기록만 하고 기준에 넣지 않는다.
- 합격이면 B 방식은 바로 돌리지 않고 보고한 뒤 사용자 지시를 기다린다.
