# linux-v1 평가 결과

방법: `docs/METHOD-FREEZE-v2.md`(고정 커밋 399d3d0) 4절, 데이터 번역 `docs/LINUX-V1-DATA-TRANSLATION.md`, 데이터셋 `docs/LINUX-V1-DATASET-BUILD.md`(linux-v1-v0).
평가 코드 `evaluation/run_linux_v1.py`(f97ec54). **결과를 보고 방법을 바꾸지 않는다.**

| 구분 | 상태 |
|---|---|
| **B 방식 (주 결과)** | **실행됨** 2026-11-23, 재생성 RE2-OB 표 사용(3절 재현 확인 합격). 4절 |
| A 방식 (보조) | 2026-11-23 실행, 2절 |
| rel14 (보조) | **실행됨** (B 방식과 함께), 4.1절 |

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

### 3.1 재현 확인 결과 (2026-11-23 15:35~15:39 KST) — **합격**

- 실행: `python -m training.freeze_v2 --features data/features/re2ob-v0 --out experiments/20261123-re2ob-v2-rebuild-check`. `systemd-run --user`로 실행했고 약 4분 걸렸다.
- 첫 실행은 `training/run_r6.py`의 `import catboost`에서 실패했다(RF·LightGBM에는 쓰지 않고 import만 한다). 고정 기록(`pip-freeze.txt`)과 같은 버전으로 catboost 1.2.10, xgboost 3.4.1을 설치한 뒤 다시 실행했다. numpy·scipy·pandas·scikit-learn·lightgbm·joblib 버전은 바뀌지 않았다. 코드는 바꾸지 않았다.

| 항목 | frozen.json (20261028) | 재현 (재생성 표) | 기준 |
|---|---|---|---|
| (a) RF 선택 | min_samples_leaf 100, max_features 0.5 | 같음 | 통과 |
| (a) LightGBM 선택 | num_leaves 15, n_estimators 300, min_child_samples 20 | 같음 | 통과 |
| (b) 내부 LOSO Avg@5 | 0.9622222222222223 | 0.9622222222222223 (차이 0.0) | 통과 |
| (b) 내부 반복 CV AUROC | 0.9960397499702127 | 0.9960397499702127 (차이 0.0) | 통과 |
| 입력 feature 목록 (rel18, 집계 58) | | 같음 | (기록) |
| ranker_rf.joblib sha256 | `4032f301…e4b5` | `e831f243…f305` | 기록만 (다름) |
| detector_lgbm.txt sha256 | `296b41ad…c5c0` | `3e1f817f…5b67` | 기록만 (다름) |

- 결론: 재생성 표는 고정 때 쓴 표와 결과상 같다. 두 내부 점수가 소수 셋째 자리가 아니라 부동소수점 전체 자릿수까지 일치했다. 모델 파일은 바이트가 다르다. 부동소수점 끝자리 차이로 나무의 분할 기준값이 달라졌기 때문으로 보인다(확인하지 않음).
- B 방식은 사용자 지시 전까지 실행하지 않는다.

## 4. B 방식 (주 결과) — 실행 전 기록 (2026-11-23, 결과 보기 전)

- **사용 표**
  - RE2-OB: Linux에서 재생성한 표(1절 해시). ranking `138efc76…65f8`, detection `f41ae001…459e`. 원래 Windows 표와 바이트는 다르지만, 3절 재현 확인에서 하이퍼파라미터 선택과 내부 점수가 같다고 확인했다.
  - linux-v1: `data/features/linux-v1-v0`. 8개 파일 sha256이 `docs/LINUX-V1-DATASET-BUILD.md` 2절 값과 같음을 실행 전에 확인했다.
- **코드와 환경:** `evaluation/run_linux_v1.py`(f97ec54, 이후 변경 없음), 시작 커밋 57e5b16. 패키지는 3.1절 재현 확인 때와 같다(numpy 2.5.4, pandas 2.2.3, pyarrow 18.1.0, scikit-learn 1.5.2, lightgbm 4.5.0, scipy 1.18.1, joblib 1.6.0).
- **방법(코드 그대로):** 반복(repetition) 3-fold. 학습 = RE2-OB 90 case + linux-v1의 나머지 fold. 하이퍼파라미터는 `experiments/20261028-re2ob-v2-freeze/frozen.json` 값이고 선택 단계는 없다.
  - 순위: RF rel18(주 방법), RF rel14(rx/tx 4개 제외, 보조), stat_combined, random. 짝지은 비교는 rf18 − stat_combined, rf14 − rf18. case 점수는 onset+60~300초 window 평균이다.
  - 탐지: LightGBM all58. 운영 문턱은 fold별 학습 정상 window 점수의 95번째 백분위다. run 경보는 onset+60초부터 제거 시점까지(fault_active / sham_active window) 문턱을 넘는 window가 2개 연속일 때다.
- **보고할 것:** 순위 표(전체·장애 종류별·fold별 Avg@5), 짝지은 비교, 탐지 AUROC/AUPRC, fold별 문턱값과 학습 행 수, run 경보율(장애 run 탐지율, 대조 run 오경보율, 비적격·no-impact 장애 run 경보율), 경보까지 걸린 시간 중앙값, 노드 보기, 급증 시 frontend 순위.
- **일관성 확인:** `--re2ob`를 주면 A 방식도 함께 다시 계산된다. 새 결과의 `method_a`가 `experiments/20261123-linux-v1-eval-a/results.json`의 `method_a`와 같아야 한다. 다르면 B 결과를 해석하지 않고 차이부터 보고한다.
- 결과가 나빠도 방법을 바꾸지 않는다. 오류가 나면 코드를 고치지 않고 멈춘 뒤 보고한다. 환경 패키지 설치는 고정 기록과 같은 버전일 때만 허용한다.
- **알고 있는 범위 차이(사실):** METHOD-FREEZE-v2 4절의 비교 행 중 B 방식의 V4(순위)와 v1 탐지기·stat_metric(탐지)은 이 코드의 method_b가 계산하지 않는다. A 방식에서만 나온다. 코드는 바꾸지 않고 그대로 실행한다.

### 4.1 B 방식 결과 (2026-11-23 15:50~15:52 KST)

- 실행: `systemd-run --user`로 `python -m evaluation.run_linux_v1 --features data/features/linux-v1-v0 --re2ob data/features/re2ob-v0 --out experiments/20261123-linux-v1-eval-b`. 2분 21초, 최대 메모리 509 MB, 오류 없음. 결과 파일: `experiments/20261123-linux-v1-eval-b/results.json`, `results.md`.
- **일관성 확인 통과:** 새 결과의 `method_a`가 `experiments/20261123-linux-v1-eval-a/results.json`의 `method_a`와 완전히 같다(JSON 전체 동일).

#### fold별 학습

| fold (시험 반복) | 순위 학습 행 | 탐지 학습 행 | 운영 문턱 |
|---|---:|---:|---:|
| 1 | 64,768 | 17,511 | 0.003532 |
| 2 | 64,537 | 17,414 | 0.003331 |
| 3 | 64,779 | 17,549 | 0.003995 |

#### 원인 서비스 순위 (적격 CPU 9 + Pod 13 = 22 case)

| 방법 | n | AC@1 (95% CI) | AC@3 (95% CI) | Avg@5 (95% CI) | MRR (95% CI) |
|---|---:|---|---|---|---|
| **RF rel18 (주 방법)** | 22 | 0.955 (0.864–1.000) | 1.000 (1.000–1.000) | **0.991 (0.973–1.000)** | 0.977 (0.932–1.000) |
| RF rel14 (보조) | 22 | 0.909 (0.773–1.000) | 1.000 (1.000–1.000) | 0.982 (0.955–1.000) | 0.955 (0.886–1.000) |
| stat_combined | 22 | 0.500 (0.318–0.682) | 0.818 (0.636–0.955) | 0.782 (0.673–0.877) | 0.672 (0.542–0.803) |
| random | 22 | 0.091 | 0.273 | 0.273 | 0.275 |

장애 종류별 (n / AC@1 / AC@3 / Avg@5 / MRR):

| 방법 | CPU 포화 (n=9) | Pod 장애 (n=13) | paymentservice 원인 (n=3, 모두 Pod) |
|---|---|---|---|
| RF rel18 | 1.000 / 1.000 / 1.000 / 1.000 | 0.923 / 1.000 / 0.985 / 0.962 | 1.000 / 1.000 / 1.000 / 1.000 |
| RF rel14 | 1.000 / 1.000 / 1.000 / 1.000 | 0.846 / 1.000 / 0.969 / 0.923 | 1.000 / 1.000 / 1.000 / 1.000 |
| stat_combined | 0.778 / 1.000 / 0.956 / 0.889 | 0.308 / 0.692 / 0.662 / 0.522 | 0.667 / 1.000 / 0.867 / 0.778 |
| random | 0.091 / 0.273 / 0.273 / 0.275 | 같음 | 같음 |

fold별 Avg@5 (fold 1 / 2 / 3):

| 방법 | fold 1 | fold 2 | fold 3 |
|---|---:|---:|---:|
| RF rel18 | 1.000 | 0.975 | 1.000 |
| RF rel14 | 0.971 | 0.975 | 1.000 |
| stat_combined | 0.900 | 0.688 | 0.771 |
| random | 0.273 | 0.273 | 0.273 |

짝지은 비교 (case bootstrap 2000, Avg@5 차이):

| 비교 | 차이 | 95% CI | 판정 |
|---|---:|---|---|
| RF rel18 − stat_combined | +0.209 | 0.114 ~ 0.318 | **나음** |
| RF rel14 − RF rel18 | −0.009 | −0.027 ~ 0.000 | 차이 없음 |

정답 순위 4위 이하: RF rel18·rel14는 없음. stat_combined는 A 방식과 같은 4 case(pod-checkoutservice-r02 4위, pod-checkoutservice-r03 5위, pod-currencyservice-r02-a2 4위, pod-currencyservice-r03 4위). stat_combined는 학습이 없어 A·B 결과가 같다.

#### 장애 탐지 (LightGBM all58)

| 항목 | 값 |
|---|---|
| window AUROC (95% CI) | **0.965 (0.930–0.990)** |
| AUPRC | 0.897 |
| window 수 / 양성 비율 | 12,473 / 0.091 |
| 적격 장애 run 경보율 | **0.944 (51/54)** |
| 대조 run 오경보율 | **0.377 (26/69)** |
| 비적격(no-impact) 장애 run 경보율 | 0.867 (13/15) |
| 경보까지 걸린 시간 중앙값 | onset + 100 s (장애 종류별: CPU·지연·Pod·급증 100 s, 손실 110 s) |

| 장애 종류 | 적격 장애 run 경보 | 대조 run 오경보 |
|---|---|---|
| cpu_saturation | 9/9 | 6/15 |
| network_delay | 14/14 | 6/15 |
| packet_loss | 10/12 | 6/15 |
| pod_failure | 13/13 | 4/15 |
| traffic_surge | 5/6 | 4/9 |

- 경보가 없던 적격 장애 run: loss-front-recommendation-r01, loss-front-recommendation-r02, surge-l2-r01.
- 오경보가 난 대조 run 26개: control-cpu-checkoutservice-r01·r02, control-cpu-paymentservice-r03, control-cpu-productcatalogservice-r02·r03, control-cpu-recommendationservice-r03, control-delay-front-currency-r01·r03, control-delay-front-product-r01, control-delay-front-recommendation-r03, control-delay-recommendation-product-r01·r03, control-loss-checkout-payment-r03, control-loss-front-currency-r01·r03, control-loss-front-product-r03, control-loss-front-recommendation-r03, control-loss-recommendation-product-r02, control-pod-currencyservice-r01, control-pod-productcatalogservice-r01-a2, control-pod-recommendationservice-r01·r02, control-surge-l1-r02, control-surge-l2-r01·r02·r03.
- 경보 판정 구간에서 가장 이른 경보 시각은 onset+100 s다. window가 rel 60·70 s에서 시작해 두 번째 window가 끝나는 때다.

#### 노드 보기 (연결 장애 26 case, B 방식 RF rel18)

| 기준 | AC@1 | AC@3 | AC@5 |
|---|---:|---:|---:|
| 양 끝 중 하나 | 0.346 | 0.808 | 0.923 |
| 출발 서비스 | 0.077 | 0.615 | 0.769 |
| 도착 서비스 | 0.269 | 0.731 | 0.808 |

#### 트래픽 급증: frontend 순위 (적격 6 case, 서술)

| case | A 방식 | B 방식 |
|---|---:|---:|
| surge-l2-r01 | 2 | 2 |
| surge-l2-r02 | 6 | 6 |
| surge-l2-r03 | 6 | 4 |
| surge-l3-r01 | 6 | 6 |
| surge-l3-r02 | 7 | 10 |
| surge-l3-r03 | 6 | 6 |

호출 경로 순위(통계 연결 점수)는 학습이 없어 B 방식에서 따로 계산하지 않는다. 2.3절 값이 그대로 적용된다.

#### 4.2 해석 (사실과 추정 구분)

**사실**
- Pod 장애 순위(RF rel18)는 A 방식 Avg@5 0.708(AC@1 0.154)에서 B 방식 0.985(AC@1 0.923)가 됐다. CPU 포화는 두 방식 모두 1.000이다. 전체 Avg@5는 0.827에서 0.991이 됐다.
- B 방식에서 RF rel18은 stat_combined보다 짝지은 비교로 나았다(+0.209, CI 0.114~0.318). rel14와는 차이가 없었다(−0.009).
- 탐지 window AUROC는 A 방식 0.873(0.829–0.917)에서 B 방식 0.965(0.930–0.990)가 됐다.
- 대조 run 오경보율은 0.377(26/69)이다. 장애 종류별 대조 run 오경보율은 0.27~0.44로 고르게 분포한다.
- 운영 문턱은 fold마다 0.0033~0.0040이다. 경보까지 걸린 시간의 중앙값은 판정 구간에서 가장 이른 시각(onset+100 s)과 같다.

**확인하지 않은 추정**
- Pod 장애 개선은 linux-v1 학습 fold에 Pod 장애 case(fold당 약 8~9 case)가 들어간 효과로 보인다. RE2-OB에는 Pod 장애가 없다. A 방식에서 우려했던 "NaN → 0" 문제(METHOD-FREEZE-v2 5절)를, linux-v1 Pod 사례로 학습하면서 다른 신호(trace 호출률 감소 등)로 보완했을 수 있다. feature 중요도나 사례별 원인은 보지 않았다.
- 탐지 AUROC 상승도 linux-v1 정상·장애 window가 학습에 들어간 효과로 보인다. 확인하지 않았다.
- 오경보율이 높은 것(37.7%)은 문턱이 낮기 때문일 수 있다. 문턱의 기준이 되는 학습 정상 window의 대부분(탐지 학습 행 약 17,500개 중 RE2-OB 9,176개 이상)이 RE2-OB 것이라 점수가 낮게 몰렸을 가능성이 있다. 경보가 판정 구간의 첫 시점에 몰리는 것도 같은 방향의 신호다. 또 번역 결정 5절의 위험(회복 직후 CPU rate[60s] 꼬리)은 sham_active 구간과 관계가 없어 원인으로 보기 어렵다. 모두 확인하지 않았고, 운영 기준점 정의는 고정 규칙 그대로 두었다.
- 비적격(no-impact) 장애 run의 경보율이 0.867로 높은 것은, 사용자 영향이 없더라도 주입 신호(CPU·지연 등)를 탐지기가 잡았기 때문일 수 있다. 대조 run 오경보율도 높아서, 둘을 나눠 해석하기는 어렵다.
- B 방식의 V4·v1 탐지기·stat_metric 비교 행은 코드가 계산하지 않는다(4절 기록). METHOD-FREEZE-v2 4절의 "주 방법과 V4의 짝지은 비교"는 A 방식에서만 있다.
