# R4 결과 해석 (RE2-OB 90 case)

전체 표: `results.md`, 수치: `results.json`, 사전 등록 계획: `config.yaml`(커밋 `8b27f87`, 결과 전에 커밋).

## 1. 원인 순위 — 사전 규칙에 따른 결론

| 방법 | features | AC@1 | Avg@5 (95% CI) |
|---|---|---|---|
| 통계 기준선 stat_combined | — | 0.794 | 0.943 (0.916–0.967) |
| joint classification (서비스×장애 분류) | 385 | 0.900 | 0.960 (0.931–0.984) |
| LightGBM metric | 26 | 0.933 | 0.967 (0.931–0.993) |
| **LightGBM core (지표+trace)** | **35** | **0.989** | **0.996 (0.987–1.000)** |
| core + opt / log / nbr / all | 38~67 | 0.978~0.989 | 0.993~0.996 |

- **core가 통계 기준선보다 낫다.** 짝지은 비교 +0.052, 95% CI 0.032~0.077로 0을 포함하지 않는다.
- **추가 묶음(opt, log, nbr, all)은 모두 "차이 없음"이다.** 사전 규칙에 따라 단순한 **core(35개)** 를 고른다.
- **metric만 쓰면 core보다 나쁘다**(−0.029, CI −0.060~−0.004). trace feature가 필요하다는 근거다. 특히 loss가 0.813 → 0.973으로 오른다.
- **60초 window는 30초와 차이 없음**(−0.002, CI −0.016~0.011). 30초를 유지한다.
- **`f_ct_mask`를 빼도 차이가 없고**, trace 있는 후보 7개로만 순위를 매겨도 같은 값이다. "trace 없음 = 원인 아님" 지름길에 기대고 있지 않다.
- **틀린 case는 1개뿐이다.** `checkoutservice_loss_1`에서 currencyservice와 productcatalogservice 다음 3위로 예측했다.

**주의: RE2-OB에서는 천장에 닿았다.** 대부분의 묶음이 0.99 이상이라, RE2-OB만으로는 묶음 사이 차이를 가릴 수 없다. "차이 없음"은 "RE2-OB로는 구분되지 않음"이라는 뜻이다.

## 2. 서비스 하나를 빼고 학습 (가장 중요한 결과)

| 학습에서 뺀 원인 서비스 | LightGBM Avg@5 | 통계 기준선 Avg@5 |
|---|---|---|
| checkoutservice | 0.889 | 0.900 |
| currencyservice | **0.800** | 0.928 |
| emailservice | 1.000 | 0.989 |
| productcatalogservice | **0.767** | 0.961 |
| recommendationservice | 0.956 | 0.939 |

- 학습 때 원인으로 본 적 없는 서비스가 원인이면, LightGBM 성능이 크게 떨어진다. currency와 productcatalog에서는 **학습 없는 통계 기준선보다 낮다.**
- 해석:
  - 같은 서비스가 원인인 사례로 학습하면 0.996이 나온다.
  - 처음 보는 원인 서비스에서는 일반화가 약하다.
  - 서비스 이름은 입력에 없지만, 서비스별 평소 패턴(호출 구조상 위치, 메모리·네트워크 비율 등)을 통해 "어떤 서비스다운 신호면 원인"을 일부 학습한 것으로 보인다.
- **linux-v1에 미치는 영향:** linux-v1의 원인 서비스에는 RE2-OB에 없던 **paymentservice**가 있다. 장애 강도도 다르다. RE2-OB로 학습한 모델을 그대로 쓰면 성능이 크게 떨어질 수 있다.
- 서비스 하나 빼기에 쓴 하이퍼파라미터는 core의 바깥 fold 선택값 중 가장 흔한 것이다. 세 fold가 모두 달라서 동률이었고, 첫 fold의 값(num_leaves 15, 100 trees, min_child_samples 20)이 쓰였다.

## 3. 탐지 (window 단위)

| 방법 | AUROC (95% CI) |
|---|---|
| 통계 기준선 stat_metric | 0.951 (0.930–0.969) |
| LightGBM core 집계 | 0.984 (0.967–0.996) |
| LightGBM all 집계 | 0.994 (0.982–1.000) |

탐지에는 사전 비교 규칙을 정하지 않았다. 그래서 묶음을 고르지 않고 결과만 보고한다(R5에서 결정).

## 4. 장애 종류 (joint classification의 부산물)

정확도 0.711, macro-F1 0.711(6종). 원인 서비스보다 장애 종류를 맞히기가 어렵다. 장애 종류 분류는 별도 모델로 R5 이후에 다룬다.

## 5. 중요 feature (core, gain 상위)

1. `f_cm_mem_limit_ratio_dmean`
2. `f_ct_in_edge_p90_lr`(들어오는 연결의 client 지연)
3. `f_cm_net_tx_pkts_dmean`
4. `f_cm_cpu_limit_ratio_dmax`
5. `f_cm_mem_limit_ratio_dmax`

메모리 변화가 1위인 것은 RE2-OB 장애 주입 방식(같은 Pod에 stress 계열 프로세스를 띄움)의 부작용일 수 있다. linux-v1에서는 이 신호가 다를 수 있다.

## 6. R5로 넘길 결론

- 고정 후보: **core 35개 feature, 30초 window, LightGBM LambdaRank**. 하이퍼파라미터는 fold마다 달랐으므로 R5에서 고정 규칙을 정한다(예: 전체 RE2-OB에서 같은 inner CV 절차로 한 번 선택).
- **일반화 약점이 확인됐으므로**, linux-v1에서는 통계 기준선(stat_combined)을 반드시 같이 보고한다. 통계와 학습 모델을 결합하는 방법은 **이번 결과를 본 뒤에 나온 아이디어**다. 쓰려면 RE2-OB에서 새 사전 등록 실험으로 따로 검증해야 한다.
- 결과를 본 뒤 바꾼 것: 없음. 실행 중 고친 것은 joint baseline의 표 변환 버그(존재하지 않는 window 행 생성) 하나다. 모델·feature·평가 규칙과는 무관하다.
- 실행 전 동작 확인용으로 core 모델 1개의 fold 1 점수(0.987)를 한 번 봤다. 그 값으로 무엇을 고른 적은 없다.
