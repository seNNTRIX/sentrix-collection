# R8 입력: linux-v1 masked 로그 + 피처 표 (linux-v1-v0)

R8(로그 의미 변화, `experiments/20261116-log-semantic-r8/PREREG.md`, 사전등록 A~D)을 **수집 PC 없이** 재현하고
시각화할 수 있도록 만든 공개용 입력이다. **원본 로그 줄은 들어 있지 않다.** 줄마다 R8의 mask 결과(문장 ID)만 있다.
임베딩·클러스터링·시각화·R8 실행 결과는 들어 있지 않다.

## 만든 방법

| 항목 | 값 |
|---|---|
| 스크립트 | `features/export_masked_logs.py` (커밋 `1de3731688d0409959805b4a3fba6f2b2cc02b4c`, 브랜치 `r8-logs-masked`) |
| mask 함수 | `features/log_semantic.py` = log-semantic-r8 `42ffbea`의 파일 그대로 (git blob `1aa0e40c0861d1f03111f4e2d437c8ea514efb5e`, 수정 없음) |
| 원본 | linux-v1 138 run(장애 69 + 대조 69)의 canonical `logs.parquet`, `features/adapters/linux_v1.py` (`list_cases`, `load_logs(keep_text=True)`, `load_metrics`) |
| 피처 표 | `data/features/linux-v1-v0` (dataset-linux-v1 `aa56d45` 시점, 표 생성 코드 `f179180`) |

```sh
python -m features.export_masked_logs export --out data/r8-input/linux-v1-v0   # logs/, log-texts, windows, cases-meta
python -m features.export_masked_logs tables --features data/features/linux-v1-v0 --out data/r8-input/linux-v1-v0
python -m features.export_masked_logs check  --out data/r8-input/linux-v1-v0 --cases \
  lv1_linux-v1-delay-front-product-r02 lv1_linux-v1-pod-paymentservice-r02 lv1_linux-v1-cpu-recommendationservice-r03
python -m features.export_masked_logs scan   --out data/r8-input/linux-v1-v0 --words <사용자 이름…>
```

줄마다 `text = mask(extract_text(message, error))`. `load_logs`에는 `error` 열이 없으므로 `error = None`이고,
이는 `log_semantic.prepare_logs`와 같다(JSON 본문의 error 필드는 `extract_text`가 직접 붙인다).

## 파일과 열

| 파일 | 내용 |
|---|---|
| `logs/<case_id>.parquet` (138개) | run별 로그 줄 표. **`load_logs`가 준 줄 전부, 그 순서 그대로**(지운 줄 없음) |
| `log-texts.parquet` | masked 문장 사전 (중복 제거). text_id는 case_id 정렬 순서로 처음 나온 순서 |
| `windows.parquet` | case별 30초 구간 표 (10초 간격) |
| `cases-meta.parquet` | case 메타 |
| `ranking.parquet` · `ranking-nodeview.parquet` · `detection.parquet` · `detection-ineligible.parquet` · `edges.parquet` | 피처 표. 원본과 **바이트 단위로 같음** (sha256 동일) |
| `cases.parquet` | 원본에서 `root`, `environment_id` 열(수집 PC 호스트 이름)만 뺌. 나머지 값은 같음 |
| `folds.json` | 원본 그대로 |
| `build-summary.json` | 원본에서 경로·호스트 이름·IP가 든 키를 뺌 (아래 보안 검사) |
| `_check.json` · `_scan.json` · `_tables-dropped.json` | 재현 검사, 보안 검사, 뺀 열 기록 |

**logs/** — `case_id`(문자열), `row`(int32, `load_logs` 순서 번호 0…n−1), `t`(float64, UTC epoch 초),
`service`(canonical 서비스 이름), `text_id`(int32 → log-texts), `err`(int8, `linux_v1.log_err`: 오류·경고 줄 1).
- `t`는 반올림하지 않았다. 원본이 나노초 단위(`timestamp_unix_nano / 1e9`)라 소수점 3자리로 자르면 최대 0.5 ms가
  달라져 구간 경계의 줄이 바뀔 수 있다. `load_logs`의 값과 비트 단위로 같다.
- 결과적으로 138 run 모두 후보가 아닌 서비스 줄 0개, 빈 문장 줄 0개다(R8은 그래도 직접 거른다).

**log-texts** — `text_id`, `text`. **windows** — `case_id`, `meta_window`(int32, case 안 구간 번호),
`w_start`, `w_end`(UTC epoch 초), `meta_rel`(= w_start − onset), `label`(`label_linux_v1`).
`features/build_linux_v1.build_case`와 같은 방식: `make_windows(onset, metric t_min, metric t_max + 1)`.
피처 표와는 **(`case_id`, `meta_window`) = (`meta_case_id`, `meta_window`)** 로 붙는다.

**cases-meta** — `case_id`, `kind`(fault/control), `fault`, `root_cause`, `repetition`, `eligible`, `onset`,
`onset_source`, `removal`, `run_start`, `run_end`, `metric_t_min`, `metric_t_max`, `n_log_lines`.
`run_end` = run_start + runtime.json `workload_elapsed_s` (부하 종료). `metric_t_min/max`는 구간 표를 만든 입력.

## 복원 방법 (R8 입력 계약: logs(t, service, message|text), windows(w_start, w_end, label))

로그 = 줄 표 + 문장 사전 join, `row` 순서로 정렬. `prepare_logs`와 같은 행은 후보 서비스·빈 문장 거르기 후
`t` 안정 정렬이다(문장은 이미 masked이므로 다시 mask하지 않는다).

```python
import pandas as pd
from features.schema import CANDIDATES
D = "data/r8-input/linux-v1-v0"
cid = "lv1_linux-v1-delay-front-product-r02"
lg = (pd.read_parquet(f"{D}/logs/{cid}.parquet")
        .merge(pd.read_parquet(f"{D}/log-texts.parquet"), on="text_id", how="left")
        .sort_values("row", kind="stable").reset_index(drop=True))
lg["service"] = lg["service"].astype(str)
prepared = (lg[lg["service"].isin(CANDIDATES) & (lg["text"] != "")][["t", "service", "text"]]
              .sort_values("t", kind="stable").reset_index(drop=True))          # = log_semantic.prepare_logs(raw)
windows = (pd.read_parquet(f"{D}/windows.parquet", filters=[("case_id", "=", cid)])
             .sort_values("meta_window").reset_index(drop=True))
# semantic_features(prepared, windows, EmbeddingCache(encoder), scope=...)
```

`features/export_masked_logs.py`의 `restore_logs`, `prepared_from_restored`, `restore_windows`가 같은 일을 한다.

## 재현 검사 (올리기 전, 통과)

| 검사 | 결과 |
|---|---|
| run별 올린 줄 수 = 원본 `load_logs` 줄 수 (138 run, `row` = 0…n−1) | 138/138 일치 |
| windows 라벨별 개수 = `cases.parquet` `windows_<label>` | 138/138 일치 |
| 피처 표 5개를 windows에 (case_id, meta_window)로 붙였을 때 못 붙은 행 / meta_rel·label 불일치 | 모두 0 (ranking 5,038 · nodeview 7,458 · detection 12,473 · ineligible 316 · edges 170,136행) |
| 샘플 3 case: 원본 → `prepare_logs` vs 복원 | 완전히 같음 |
| 샘플 3 case: 원본 windows(재계산) vs 복원 | 완전히 같음 |
| 샘플 3 case: `semantic_features`, B(해싱 인코더) scope="service" / "all" | 완전히 같음 (NaN 위치 포함) |

샘플: delay-front-product-r02 (network_delay, 249,672줄), pod-paymentservice-r02 (pod_failure, 239,549줄),
cpu-recommendationservice-r03 (cpu_saturation, 249,674줄). 각 1,694행(154구간 × 11서비스), 유효 1,192 / 1,080 / 1,185행.
MiniLM(C·D)은 받지 않고 B로만 확인했다. C·D는 같은 `prepared`·`windows`를 쓰므로 입력은 같다.

## 보안 검사 (전수, 통과)

대상: `log-texts`의 text와 모든 표(parquet 13개 종류 + logs 138개 + JSON 2개)의 모든 문자열 열·JSON 키·값.
패턴: IPv4, IPv6, 노드 호스트 이름(수집 PC 이름), Pod 이름(`…-xxxxxxxx(xx)-xxxxx`), UUID, 이메일, 사용자 이름,
절대 경로(`/home/`, `/Users/`, `C:\`), 8자리 이상 숫자열. 결과: **모든 패턴 0건**.

예외 규칙 (2026-11-23 결정):
1. `0x`로 시작하는 16진 메모리 주소(`0x[0-9a-f]+`)는 검사에서 뺀다. 적용 3건 (log-texts의 frontend 시작 로그 3개).
2. 열 이름(JSON은 키 경로)이 `view`, `*_commit`, `*_sha256`인 곳의 16진 해시 값은 검사에서 뺀다(재현 기록).
   적용 144건 (cases.parquet `view` 138, build-summary.json `code_commit` 1 · `code_sha256` 4 · `schedule_sha256` 1).

복사한 표에서 뺀 항목:
- `cases.parquet`: `root`, `environment_id` (호스트 이름)
- `build-summary.json`: `roots[].name` · `roots[].environment_id` (호스트 이름), `roots[].path` · `schedule` (로컬 경로),
  `excluded_attempts[].decision_root` · `excluded_attempts[].run_folders` 값 (호스트 이름),
  `excluded_attempts[].failure_cause` (모든 항목에서 키째로 뺌: 수집 PC 운영 기록 자유 서술, IP·호스트 이름 포함)
- ranking · ranking-nodeview · detection · detection-ineligible · edges · folds: 뺀 것 없음

## 알려진 사항

- mask가 Go 포인터(`0x…`, 예: frontend 시작 로그의 `cartSvcConn:0xc000681400`)를 가리지 않아 고유 문장이 조금 늘어남.
  민감 정보 아님. R8 원래 mask 결과와 같게 하려고 그대로 둠.
- redis-cart 저장 로그(`1:M 27 Oct <NUM> 04:43:<NUM> * Background saving started by pid 25` 등)는 시각·PID가 남아
  run마다 새 문장이 된다(run당 약 36개, 고유 문장 5,019개 중 대부분). 이것도 R8 mask 그대로다.

## 크기 · 줄 수

원본(참고): 138 run `logs.parquet` 3,770 MB, 36,343,407줄 (canonical 서비스가 아닌 줄 포함).
올린 줄: 34,931,489 (장애 69 run 17,766,781 · 대조 69 run 17,164,708). 고유 masked 문장 5,019개.
폴더 합계 227,358,716 bytes (README 제외), 파일 최대 3.5 MB.

| 파일 | 용량 (bytes) | 행 수 | sha256 |
|---|---:|---:|---|
| `_check.json` | 2,246 | - | `67dddb6c4ea8901d4373769705a94f7903b43a0d809707d786d00a358c115822` |
| `_scan.json` | 1,087 | - | `032c954832367de630df786e5176415b9d2428f53d4fbbb0839bfa26514fc0b7` |
| `_tables-dropped.json` | 558 | - | `57387dcd06a1fb3183f068f626c8aa632106587fab334e90cd874f3bf7a27f27` |
| `build-summary.json` | 5,890 | - | `49b9b123dcd3672327baf1c77171ef5f18a977e678928a40638bbe6b12b8bb63` |
| `cases-meta.parquet` | 15,314 | 138 | `ca4916756fb5c68d8658853b85840e58a26b95e5ac575e2a50778065e59cb288` |
| `cases.parquet` | 40,074 | 138 | `8c8200ec705824b6fc8b4c46f18126e4be7bd6ce60c913e18172a153a4a68bba` |
| `detection-ineligible.parquet` | 133,752 | 316 | `211a3baa80aefb82303dac58d488cd600a3b5ab7f125bcbfdc5995d6d9652fee` |
| `detection.parquet` | 3,499,944 | 12,473 | `c25c0b35bbbb11863c55e86e9535a9b719512edb1942d921a333fd9b6834be1a` |
| `edges.parquet` | 1,661,510 | 170,136 | `d82c1993acd489cf46815bca285206708f9857ebcd78433b7751ea54f913cafd` |
| `folds.json` | 6,828 | - | `58b81f5bc3139a292dde1ccb527882107fc9778b32d10ed1235935398a9c40cd` |
| `log-texts.parquet` | 42,275 | 5,019 | `eba77088a78ba93fa5acad513dc513c97ab5658ad38c2fb75798cca12d8ce2a3` |
| `ranking-nodeview.parquet` | 1,554,725 | 7,458 | `8f435d9f6e4a4749fdfb95f7b543986e358af9a612d0b660904f791234521486` |
| `ranking.parquet` | 1,015,201 | 5,038 | `34c4c4f8876eea9abbef6d34e39d80f158dc40cda853c8683e72caaf7dc39ec6` |
| `windows.parquet` | 132,607 | 21,267 | `9ccb5bbad6373e610a16939c2f40ee130f1879d639b6665c44896711db80ba94` |

logs/ 합계: 파일 138개, 219,246,705 bytes, 34,931,489행. 최대 파일 2,031,137 bytes.

<details><summary>logs/ 파일별 (138개)</summary>

| 파일 | 용량 (bytes) | 행 수 | sha256 |
|---|---:|---:|---|
| `logs/lv1_linux-v1-control-cpu-checkoutservice-r01.parquet` | 1,582,864 | 249,465 | `27e9102ca37479be6c66a9aaf3cae19901805cbf7c8f98dc233dbc8614c05307` |
| `logs/lv1_linux-v1-control-cpu-checkoutservice-r02.parquet` | 1,577,104 | 249,536 | `227ae13657deca914ea15492466fcfbff4fd40f4d08114b7bb67562d197db112` |
| `logs/lv1_linux-v1-control-cpu-checkoutservice-r03.parquet` | 1,560,653 | 249,606 | `3fdfcb9b0e97a4ced2ff29a9bd257085353c28f25f3856f60932127c9d417005` |
| `logs/lv1_linux-v1-control-cpu-currencyservice-r01.parquet` | 1,581,446 | 249,468 | `50e5cc1c9e5f2da7968fbf2b54ce6d9895d7eedfcc49a52ebb6c49d7878b53c0` |
| `logs/lv1_linux-v1-control-cpu-currencyservice-r02-a2.parquet` | 1,586,669 | 249,605 | `39c83e729e51b0ee5ae4a7c6fa38ceb61404c2417071067bb1afec58347f4835` |
| `logs/lv1_linux-v1-control-cpu-currencyservice-r03.parquet` | 1,583,048 | 249,605 | `c9f03f9621d2539313f5d6e1c196d36009b8c5dca0f2d8b316dfae505d318c3b` |
| `logs/lv1_linux-v1-control-cpu-paymentservice-r01.parquet` | 1,583,994 | 249,673 | `78843cdc9a97a3b5ba567154988be0b344f108a915f2419e05b95fb2b614f799` |
| `logs/lv1_linux-v1-control-cpu-paymentservice-r02.parquet` | 1,587,082 | 249,607 | `dce633a598631c50aeffb93eb4744240b3c4bd4e2881170633dbceebafc9a735` |
| `logs/lv1_linux-v1-control-cpu-paymentservice-r03.parquet` | 1,562,709 | 249,674 | `dd48d02ac9706efc6757d037120f804a05c1d3333cf02f0976694ead707efadc` |
| `logs/lv1_linux-v1-control-cpu-productcatalogservice-r01.parquet` | 1,588,087 | 249,605 | `465b3f1ee14382300ee57571b00128608df3dab1b3540f0961ac6ba4d25855b3` |
| `logs/lv1_linux-v1-control-cpu-productcatalogservice-r02.parquet` | 1,583,868 | 249,742 | `a0f5b1a050b34182727c995db8335217016bac29f6108a09ea98e9ff69edfc96` |
| `logs/lv1_linux-v1-control-cpu-productcatalogservice-r03.parquet` | 1,559,959 | 249,674 | `7c19ceec266e4629ab8d5f5213d1f1c2c7af83da69b3db114f0849c7519d1588` |
| `logs/lv1_linux-v1-control-cpu-recommendationservice-r01.parquet` | 1,560,755 | 249,533 | `e91a48d4fafae57f47dec3f56fbc55c33a2815db2ebf443d47dfd899adbd8cd1` |
| `logs/lv1_linux-v1-control-cpu-recommendationservice-r02.parquet` | 1,587,387 | 249,743 | `5cdc28a94534026deca1562a0b464ee4eb28c1875087ad7a05a4668fc4b9cfdf` |
| `logs/lv1_linux-v1-control-cpu-recommendationservice-r03.parquet` | 1,551,703 | 249,674 | `1b3ba355914c69395f5a43948b77b1249ca47e4863369b2177606af372f47e30` |
| `logs/lv1_linux-v1-control-delay-checkout-payment-r01.parquet` | 1,575,923 | 249,467 | `168865c3ffb66ae4ac30b7c1c4b447258b43a3218c8ccb716e0d7f2b8a5dc4d0` |
| `logs/lv1_linux-v1-control-delay-checkout-payment-r02.parquet` | 1,585,158 | 249,606 | `68edbd487ca9788b8253876dc741c844572f7283559c53ab335c2eef8ce0e267` |
| `logs/lv1_linux-v1-control-delay-checkout-payment-r03.parquet` | 1,566,539 | 249,606 | `bc468812a600b4088b2025aaa386c53e370a5aa136116ae5d1f81c128d6910d6` |
| `logs/lv1_linux-v1-control-delay-front-currency-r01.parquet` | 1,556,874 | 249,605 | `b167b1919aa8addb40b6172826b7b2ae9053104c922898305a759264eaf3a43b` |
| `logs/lv1_linux-v1-control-delay-front-currency-r02.parquet` | 1,584,407 | 249,605 | `c7a04752dcece315f289b3a3a6247d764a0268ea2e697b60b6009fdf75f38816` |
| `logs/lv1_linux-v1-control-delay-front-currency-r03.parquet` | 1,561,668 | 249,605 | `4a7e9ab977b598af2d12b46d78d4e1c0d6a078586c479c1ee3529b764812ad48` |
| `logs/lv1_linux-v1-control-delay-front-product-r01.parquet` | 1,562,582 | 249,673 | `1da09b910468fc2c7a22cfb2470ddb1621a8e13f36d75e18cf1cd65e2e9875d9` |
| `logs/lv1_linux-v1-control-delay-front-product-r02.parquet` | 1,572,764 | 249,605 | `f14e7a7ecbc95718f05538e2e98684d5314929eaec2c7283063d7cc239befdfb` |
| `logs/lv1_linux-v1-control-delay-front-product-r03.parquet` | 1,583,708 | 249,608 | `b7101ab6e5d45821dc4b33ad57ff38bc69ec4cd802fed447950d543563f3d93b` |
| `logs/lv1_linux-v1-control-delay-front-recommendation-r01.parquet` | 1,585,915 | 249,604 | `7adf5dfa7dc75ff2446e3bdcf952990b52e87853bc53e6e59a54236126ada4a9` |
| `logs/lv1_linux-v1-control-delay-front-recommendation-r02.parquet` | 1,579,587 | 249,741 | `571093b945f2ae1d674cc3e71ebd534a7c385136178c75b691368b07e386dc77` |
| `logs/lv1_linux-v1-control-delay-front-recommendation-r03.parquet` | 1,569,522 | 249,675 | `e9625a7f3e4f0640a869bca3904f47e31a6967ac14e3b1bd3c6543cdf51df2b3` |
| `logs/lv1_linux-v1-control-delay-recommendation-product-r01.parquet` | 1,560,707 | 249,606 | `ce09336f63badb19a0fd71b4f045bb8792cc33fe6c79c9cb8c326438f84c5cfd` |
| `logs/lv1_linux-v1-control-delay-recommendation-product-r02.parquet` | 1,585,748 | 249,538 | `837796989ea38ca994d8fc59ae40528dd95ebc77081f38d28dff70780d0276ae` |
| `logs/lv1_linux-v1-control-delay-recommendation-product-r03.parquet` | 1,586,220 | 249,605 | `19d0dbde3f8c2515226ec9bd4a51851e77832f33c0215df397728a0d3a45f1d1` |
| `logs/lv1_linux-v1-control-loss-checkout-payment-r01.parquet` | 1,576,975 | 249,603 | `6c519342e96d4e2f695e35c5be3516ad53edab19e1acb2b5d6461268fdb64b60` |
| `logs/lv1_linux-v1-control-loss-checkout-payment-r02.parquet` | 1,589,841 | 249,535 | `57084e65df62ba2237f64a3db0d765aa7bae197f05eb94cd3ed7815761692d5c` |
| `logs/lv1_linux-v1-control-loss-checkout-payment-r03.parquet` | 1,590,353 | 249,674 | `044ac6dc141fef46531a95e1165014959f2250aa8a28877686599d1e35b17399` |
| `logs/lv1_linux-v1-control-loss-front-currency-r01.parquet` | 1,582,675 | 249,674 | `752f00ebd9cbf639c6aff76baa26f336dfc6bff03a91dd1ffaa0af3afe88e997` |
| `logs/lv1_linux-v1-control-loss-front-currency-r02.parquet` | 1,593,463 | 249,608 | `b052a4bd793c3ff76ce5feeb22be7740e9bff73d12887c1adcc1d21cf97e078d` |
| `logs/lv1_linux-v1-control-loss-front-currency-r03.parquet` | 1,559,186 | 249,536 | `75887d66543e00fb23915ad498d2bc7b06e29d3bd8c397dd69f035977a2df6bc` |
| `logs/lv1_linux-v1-control-loss-front-product-r01.parquet` | 1,560,046 | 249,672 | `c2856a6340a4902683d1ef322af7306ed821f8ae8cdb6f4e322435b854a9427e` |
| `logs/lv1_linux-v1-control-loss-front-product-r02.parquet` | 1,560,295 | 249,673 | `c139b0abc4f2b79dd61c5c1a4ed035ad93755d6f0f756773a75bbf4733c7d249` |
| `logs/lv1_linux-v1-control-loss-front-product-r03.parquet` | 1,559,818 | 249,538 | `d6bac841d946012c25a58c83f179a804201920379f8b0950fb1f6591e5054639` |
| `logs/lv1_linux-v1-control-loss-front-recommendation-r01.parquet` | 1,586,567 | 249,673 | `3b2c6bce41baa2eb2684854a5273967b6cbf32e0c25de8388112fc49fbfbae2b` |
| `logs/lv1_linux-v1-control-loss-front-recommendation-r02.parquet` | 1,561,941 | 249,604 | `d0e2e284b711a157abacd538bac24e3126f61cecd0cc053a6b8dc0a857508e7c` |
| `logs/lv1_linux-v1-control-loss-front-recommendation-r03.parquet` | 1,563,189 | 249,604 | `af1b862160d2f24c75f908180c33fce10c124f02b5ab885b2e72e4531679d3f5` |
| `logs/lv1_linux-v1-control-loss-recommendation-product-r01.parquet` | 1,586,075 | 249,674 | `943a080ca85f1754748aec067aab0997faa0a2f5b80957b94b278e526407b1bc` |
| `logs/lv1_linux-v1-control-loss-recommendation-product-r02.parquet` | 1,587,378 | 249,675 | `d355eeddcabaff6be88b0661cd159df2ce3dda6ee085bb784997b6927c02f9d6` |
| `logs/lv1_linux-v1-control-loss-recommendation-product-r03.parquet` | 1,557,507 | 249,399 | `ab7ee18c5fb11d45e4e1ae2b9728d1e179c1d86755959e73651c2cbd9eced1c7` |
| `logs/lv1_linux-v1-control-pod-checkoutservice-r01.parquet` | 1,589,755 | 249,673 | `dd92e70a2be0ff14a331e3324d62c8bf6bf1122e33ffd1e68a55c8307bb7adb3` |
| `logs/lv1_linux-v1-control-pod-checkoutservice-r02.parquet` | 1,584,892 | 249,536 | `4007fa55b3d3a70320d511da1f603c8003284ccc909f8c3438d9d99004c09b3a` |
| `logs/lv1_linux-v1-control-pod-checkoutservice-r03.parquet` | 1,560,522 | 249,673 | `b7abf9ce094acb963db3aab3a2159a359ed9a4516f9fe513365f5fef726bfcaf` |
| `logs/lv1_linux-v1-control-pod-currencyservice-r01.parquet` | 1,582,831 | 249,535 | `65e4fcf9b9210c8928ce6898cee37115aeac91267e2dc7489891f34e6633f017` |
| `logs/lv1_linux-v1-control-pod-currencyservice-r02-a2.parquet` | 1,560,853 | 249,745 | `4638142afcbae343c64a80c79fe161a2af644a97b82c258d15bb7452eb68e4ea` |
| `logs/lv1_linux-v1-control-pod-currencyservice-r03.parquet` | 1,559,794 | 249,673 | `bdf0f5ca9f6477fc40fd6efb09cd053cbc7c42e1ce78ca6021df93c39d8bfcfa` |
| `logs/lv1_linux-v1-control-pod-paymentservice-r01.parquet` | 1,586,645 | 249,604 | `cd04ec62f2f22ce91379f766f3e14cad4088992bd6b240f68d9f5bb0bafa9a86` |
| `logs/lv1_linux-v1-control-pod-paymentservice-r02.parquet` | 1,555,790 | 249,536 | `2e9addad8f6fc03e300885ff5e55ca393e85a775581e14578ba0f2eda75c5efa` |
| `logs/lv1_linux-v1-control-pod-paymentservice-r03.parquet` | 1,584,869 | 249,606 | `b3730f60ad81a44b0ff7ff166992467f928ba9b1facb83aecb0beb9a543a9e2c` |
| `logs/lv1_linux-v1-control-pod-productcatalogservice-r01-a2.parquet` | 1,561,621 | 249,605 | `cc41626073594e9a64a5eaf03bb9756867afe6dbe24e5a55b9be344edcab2213` |
| `logs/lv1_linux-v1-control-pod-productcatalogservice-r02.parquet` | 1,561,864 | 249,673 | `e0d58c6c33fbd647de85856db30d46ab8fd79fa7e004cac622d463a5c215b940` |
| `logs/lv1_linux-v1-control-pod-productcatalogservice-r03.parquet` | 1,565,838 | 249,536 | `57d1604e6b05957fc1e0c36c17e2c45dd67c820232e176a33ec8fde893fc3df9` |
| `logs/lv1_linux-v1-control-pod-recommendationservice-r01.parquet` | 1,588,740 | 249,604 | `eb71e7d31f9a086b53b440204f84f90048ff21fea8c475bf0051b4d438a80d92` |
| `logs/lv1_linux-v1-control-pod-recommendationservice-r02.parquet` | 1,559,585 | 249,674 | `cac1dd0dfac032cb077db8579db271e4307c188b97a763417724471ae037bf34` |
| `logs/lv1_linux-v1-control-pod-recommendationservice-r03.parquet` | 1,560,044 | 249,674 | `d39b6d41fda53030524386c63ba0af2a36fbef7a4e58122d8bd336d339423424` |
| `logs/lv1_linux-v1-control-surge-l1-r01.parquet` | 1,557,996 | 249,674 | `eb77be52ce405d851e0315d5a34b8094fcbe8e40446c9790250bd2f17306f265` |
| `logs/lv1_linux-v1-control-surge-l1-r02.parquet` | 1,585,645 | 249,605 | `d6fe3588d339cac4e9dbd72aabe9b3fc39db987eacac63d648497cf73bb5b3db` |
| `logs/lv1_linux-v1-control-surge-l1-r03.parquet` | 1,587,021 | 249,672 | `1e1a41280268f8ef8222ef4a580c31775b283ef12e44eca76d84ff0471fe579e` |
| `logs/lv1_linux-v1-control-surge-l2-r01.parquet` | 1,290,816 | 191,021 | `5a0318428e8a98f84e3824c89a0caf3866876dd7aa78700013c828e157f64164` |
| `logs/lv1_linux-v1-control-surge-l2-r02.parquet` | 1,576,931 | 249,535 | `eabec41c07526184ff273a65f502f993ce3f687aa44ee4638deb2a2f49987449` |
| `logs/lv1_linux-v1-control-surge-l2-r03.parquet` | 1,558,595 | 249,537 | `d941fff4bac7dc5db94428a30cba35ec9ff915c406311a2a26e6e17c401af552` |
| `logs/lv1_linux-v1-control-surge-l3-r01.parquet` | 1,583,295 | 249,607 | `b65900839b346e8a3b069875755b896e09dca8be9cfe1a3067c6000834f98f58` |
| `logs/lv1_linux-v1-control-surge-l3-r02.parquet` | 1,584,372 | 249,605 | `c608fb3e807f5ebba98b51549539601f521329c1089d32f674f3d753157fea6a` |
| `logs/lv1_linux-v1-control-surge-l3-r03.parquet` | 1,585,716 | 249,604 | `a6a4fc941a0d87b36d6d5ab654a6252e8186bb0b70637a3398e85c8d2a6b4d31` |
| `logs/lv1_linux-v1-cpu-checkoutservice-r01.parquet` | 1,585,823 | 249,535 | `381a84dfb9a3a1ceb44ba08fb7137e7f84eb6e2fc5e85a00497eb983d967bd0e` |
| `logs/lv1_linux-v1-cpu-checkoutservice-r02.parquet` | 1,585,530 | 249,744 | `64358e17e47c825b38fb8f4e0312efe701bab06bfe1c2b76f6655fd0536ce0ba` |
| `logs/lv1_linux-v1-cpu-checkoutservice-r03.parquet` | 1,561,240 | 249,674 | `c7b5503e6ea50ffc4f0e975e71150d430399961c2f6e3ca59902ca797e92fbf4` |
| `logs/lv1_linux-v1-cpu-currencyservice-r01.parquet` | 1,623,495 | 249,535 | `ef610cf115a2412edee50664c569f87953d1dad5e30f7498600b5b8e1e006942` |
| `logs/lv1_linux-v1-cpu-currencyservice-r02-a2.parquet` | 1,620,092 | 249,605 | `fafbe04dc6a2cad130416a017c8ad0c9e8193b2f49922268897b25180564731f` |
| `logs/lv1_linux-v1-cpu-currencyservice-r03.parquet` | 1,617,635 | 249,536 | `2b2827d8b1f855163c00bbf72e5d7cd197c0360cc1254ae7299eeae975ae8ccb` |
| `logs/lv1_linux-v1-cpu-paymentservice-r01.parquet` | 1,560,738 | 249,673 | `6fe25a8481311c8a5ee59d033bfe9ba8a3aa8ef003fae326032c51955bd785eb` |
| `logs/lv1_linux-v1-cpu-paymentservice-r02.parquet` | 1,561,765 | 249,674 | `b5688f7004aa4ed293ec3c2887ce79fa61b9cd9d1570f678c76a488cfdfb3d58` |
| `logs/lv1_linux-v1-cpu-paymentservice-r03.parquet` | 1,584,818 | 249,605 | `d0c67f9b15aa33b07f2882cdb81ed034d398cc602def5ad124c568c3065ad581` |
| `logs/lv1_linux-v1-cpu-productcatalogservice-r01.parquet` | 1,597,537 | 249,534 | `d7c3d1af679d079cea89f96c7b9ffdf307312920decab3f375722ab6d43c96e7` |
| `logs/lv1_linux-v1-cpu-productcatalogservice-r02.parquet` | 1,590,864 | 249,673 | `42b804899e1e79ee2d39d71a7b77a3c077749a37f2b77549be6ba7c5b5629261` |
| `logs/lv1_linux-v1-cpu-productcatalogservice-r03.parquet` | 1,589,636 | 249,536 | `6442879e2c4215e32455e66f6d2fb4c1dcf12df6803e7276f96e35cf71a11a8e` |
| `logs/lv1_linux-v1-cpu-recommendationservice-r01.parquet` | 1,566,756 | 249,744 | `91e4ba73b0c9f89c5a8fe2efb920f95f449f8852fb7adf12b430689618c7ed6b` |
| `logs/lv1_linux-v1-cpu-recommendationservice-r02.parquet` | 1,590,069 | 249,672 | `98e60a8ab0e362b4acebea1986fd6e70f84ae605297a22bf6535f820000b07b9` |
| `logs/lv1_linux-v1-cpu-recommendationservice-r03.parquet` | 1,591,256 | 249,674 | `8f253a457d301bb87b47a35cfe86c032755479b148e4f9bd1731e2bcc4e424b0` |
| `logs/lv1_linux-v1-delay-checkout-payment-r01.parquet` | 1,587,712 | 249,674 | `2dc3ecc9ef5e0e763e22583cf2cbd548d556458fd1346e74d7d35488ad61232b` |
| `logs/lv1_linux-v1-delay-checkout-payment-r02.parquet` | 1,561,344 | 249,672 | `b1e873a326e6445fca9f487be50f6b200cd84dfcb9e82f8059018ef53f7a6535` |
| `logs/lv1_linux-v1-delay-checkout-payment-r03.parquet` | 1,588,604 | 249,603 | `22769c0a300bf6c22ab36da7ccb504f4ecb8ac4d7059ce42f0eaf29574977172` |
| `logs/lv1_linux-v1-delay-front-currency-r01.parquet` | 1,617,804 | 249,675 | `7dc6da4ccb0dad43eec30f01433a04f352cf36c3f855d1fed695d4ea49f7add0` |
| `logs/lv1_linux-v1-delay-front-currency-r02.parquet` | 1,615,519 | 249,672 | `639f8e7fb4e829ba9f4bfdbd800960fa5a2b29091a3405c87a62a5f6641eb4e1` |
| `logs/lv1_linux-v1-delay-front-currency-r03.parquet` | 1,618,171 | 249,605 | `34f9b2ebf55cc39b9b9806f274d1343b0066fd51c8fe04996d650d9685ed41db` |
| `logs/lv1_linux-v1-delay-front-product-r01.parquet` | 1,611,531 | 249,605 | `5fad0ed10f79e1105baa6c28fded1e22f0bffa9aa16cad5f4803146b1594ef3e` |
| `logs/lv1_linux-v1-delay-front-product-r02.parquet` | 1,618,295 | 249,672 | `fa7d4394b5569fdb84d8b18849c3878826a19237c80e50ea3a58a120a12eaf9b` |
| `logs/lv1_linux-v1-delay-front-product-r03.parquet` | 1,613,111 | 249,608 | `39fa9004c6e997f855a2179b10c393b9606ac8a00e69c6f374f3c28f044b42cf` |
| `logs/lv1_linux-v1-delay-front-recommendation-r01.parquet` | 1,596,007 | 249,535 | `c5e5aaa5b6dce4377aeb2c0c4b10e3db24c2bf3ef86222755ca49cfa5843b843` |
| `logs/lv1_linux-v1-delay-front-recommendation-r02.parquet` | 1,594,713 | 249,743 | `aab25f5872ee9ac65c178cf3b5b7f371c59296c2963642d3a5c27f345dc3187d` |
| `logs/lv1_linux-v1-delay-front-recommendation-r03.parquet` | 1,597,373 | 249,744 | `4a4ad6816053db0a15abb8936f7c4306d73f1630b602eea50b62e8e87f971558` |
| `logs/lv1_linux-v1-delay-recommendation-product-r01.parquet` | 1,577,303 | 249,673 | `9efe6c8cfa0d7a01779f5a4fd79d89fb13b30f0a4f25cd6a756be36ea6ab300b` |
| `logs/lv1_linux-v1-delay-recommendation-product-r02.parquet` | 1,568,552 | 249,673 | `610581e3951bf7e3ca4dcd05899bc231cf33f74cabd7f3be1278a58b575bb414` |
| `logs/lv1_linux-v1-delay-recommendation-product-r03.parquet` | 1,598,884 | 249,674 | `a75030b06e34d7f27d892c644ca1c337f7f09b13685380a09583eb4a6d9c06c1` |
| `logs/lv1_linux-v1-loss-checkout-payment-r01.parquet` | 1,584,252 | 249,606 | `fbf500fddf5b694273b40e07c971f4c89429f0057317ccf274a520d3e64b7ec6` |
| `logs/lv1_linux-v1-loss-checkout-payment-r02.parquet` | 1,574,581 | 249,674 | `994bd975cfbd145c42ac8a4ba52f419be86200fb38ef85cc416c2164321978c2` |
| `logs/lv1_linux-v1-loss-checkout-payment-r03.parquet` | 1,586,908 | 249,673 | `33193d03bf882d30f0f414f7378a8fb2d861f0046c7e777beec0430a7510e4c2` |
| `logs/lv1_linux-v1-loss-front-currency-r01.parquet` | 1,587,202 | 249,535 | `7ef5830021145603c04051f0365ef0a2f7e62a08dc23443822c03fb0502acf9c` |
| `logs/lv1_linux-v1-loss-front-currency-r02.parquet` | 1,589,598 | 249,604 | `c4f0e6e6933373c5bc56c92955926b1ebe53471f7a5c06414d4d1da526781bef` |
| `logs/lv1_linux-v1-loss-front-currency-r03.parquet` | 1,587,515 | 249,674 | `dccfb7f3409dadca479cc32ff67b1843b8f2300a89193c6c77471739056aeaf4` |
| `logs/lv1_linux-v1-loss-front-product-r01.parquet` | 1,563,630 | 249,536 | `118466d8406d59beeb74f24bd5f663420a6d40626d43be2b42411d70da3b6cc9` |
| `logs/lv1_linux-v1-loss-front-product-r02.parquet` | 1,587,658 | 249,607 | `2204d692ad08b573550c9eb5c68d031c9cadeb7e65fd4bd403d7d5940af2ba56` |
| `logs/lv1_linux-v1-loss-front-product-r03.parquet` | 1,590,338 | 249,605 | `6860d49272f9ef24dc505708d382a7dd182c5406bfe367932004258fbc8211a6` |
| `logs/lv1_linux-v1-loss-front-recommendation-r01.parquet` | 1,583,495 | 249,536 | `6aeea4344a62ca16e21e909dfffab12f858ac2d94eceab7625804ca2f7c3177e` |
| `logs/lv1_linux-v1-loss-front-recommendation-r02.parquet` | 1,570,540 | 249,604 | `69429fc316b9f199214002ce96638bd0528cc0f15b5b077e1f2f55f07e0d1b32` |
| `logs/lv1_linux-v1-loss-front-recommendation-r03.parquet` | 1,552,488 | 249,674 | `d7c0fafbccec019144dde88ddc57f6ec2bf629393f0cb1e72abec9201ba88490` |
| `logs/lv1_linux-v1-loss-recommendation-product-r01.parquet` | 1,585,670 | 249,536 | `211f538fb9745365fc6f807253dd85239930025fc10ad0b1691f7b1f6b6a1322` |
| `logs/lv1_linux-v1-loss-recommendation-product-r02.parquet` | 1,562,840 | 249,743 | `49d55c7a58fab6734586966020cae1024300bd037e74eac8dd6e7f02a2e9426f` |
| `logs/lv1_linux-v1-loss-recommendation-product-r03.parquet` | 1,577,219 | 249,742 | `06214823ed862e3b83ff6a1d651710886f9a8190ae8d3d2407fc3df2340faf1d` |
| `logs/lv1_linux-v1-pod-checkoutservice-r01.parquet` | 1,487,296 | 232,708 | `1348dab3d8d4fd9a6786910e4df3f539856b29a08f2f4d77ba529182f13d8413` |
| `logs/lv1_linux-v1-pod-checkoutservice-r02.parquet` | 1,523,098 | 238,032 | `081b99993df94b500dbcdbad0ec56d3f2fc181e72f7d84aef59f823404a6367f` |
| `logs/lv1_linux-v1-pod-checkoutservice-r03.parquet` | 1,506,126 | 233,624 | `1e26af5696a2d79b43a797d72be426151408f7154427e51d353c8b3ed9d5c338` |
| `logs/lv1_linux-v1-pod-currencyservice-r01.parquet` | 1,348,504 | 209,017 | `dfc37a888a8387fdbaf3f7c38cb5b83e4b6c8205af5b631ef6bcf3bde9c6105d` |
| `logs/lv1_linux-v1-pod-currencyservice-r02-a2.parquet` | 1,395,814 | 217,730 | `85fe33863047093e0f55d37f5b12828985abef01a4a1311e3482b65276d70934` |
| `logs/lv1_linux-v1-pod-currencyservice-r03.parquet` | 1,369,024 | 209,034 | `273855c8e6240f2e4e662aeed9653b80515d98ca0ab8655bdd72768e0f293317` |
| `logs/lv1_linux-v1-pod-paymentservice-r01.parquet` | 1,521,709 | 240,007 | `a56604d9c1de6e39cdd58b765314757ff51436889a10b6b137ed0e99ef37ce58` |
| `logs/lv1_linux-v1-pod-paymentservice-r02.parquet` | 1,514,583 | 239,549 | `996c3f4ca8e180912e4acd5d5c6f2bb0cdea050764fc02ac5e468e4ae55909a2` |
| `logs/lv1_linux-v1-pod-paymentservice-r03.parquet` | 1,546,547 | 242,177 | `bd2156e765a02a987fad7bae2c259e690a9b6e33a4b8457a398f2faf2c3eeb61` |
| `logs/lv1_linux-v1-pod-productcatalogservice-r01-a2.parquet` | 1,637,470 | 274,623 | `e26d4ba3015c02e59ee12023fc3e9c9b08d69263e6917232e261d40e35241182` |
| `logs/lv1_linux-v1-pod-productcatalogservice-r02.parquet` | 1,710,349 | 300,135 | `c6608b2812c011491a1b85059d98d4cb645676b05c707fbff52b636b5492e812` |
| `logs/lv1_linux-v1-pod-productcatalogservice-r03.parquet` | 1,663,929 | 282,164 | `f584e7cd0492452e1612716c7d21795b568e716e161a9b628b0c31642523e671` |
| `logs/lv1_linux-v1-pod-recommendationservice-r01.parquet` | 1,581,713 | 248,514 | `70f062d4cfa91ef58790648ea4a7a818abf3fd6129438148d1d2239147a2f450` |
| `logs/lv1_linux-v1-pod-recommendationservice-r02.parquet` | 1,575,637 | 248,656 | `f79e32194942af753793d6b7f62c779358761c05cbbeb24c31555d3978a2aa73` |
| `logs/lv1_linux-v1-pod-recommendationservice-r03.parquet` | 1,577,139 | 248,626 | `36056edae5d83ae8c46771e4ad5066a2d16d15677dd6f59a7abba4f6a45bd6ad` |
| `logs/lv1_linux-v1-surge-l1-r01.parquet` | 1,740,787 | 299,285 | `572cd85a807e9f17efa65305442b8f16b4c24b15fc4816fdf7c8c08f011e55de` |
| `logs/lv1_linux-v1-surge-l1-r02.parquet` | 1,737,751 | 299,423 | `077e9416ab49efff553775b646a538358cdeddd6ade85858757558515ec84042` |
| `logs/lv1_linux-v1-surge-l1-r03.parquet` | 1,767,845 | 299,219 | `f49a874cd716821a27a06f80bf4324e483b7767fefb3e4a3fd83b7028ef4a64b` |
| `logs/lv1_linux-v1-surge-l2-r01.parquet` | 1,461,807 | 225,773 | `7d514b2629c54dd75614a229cf2a5e1410a976a9616888a3c572fa75fd4a4e48` |
| `logs/lv1_linux-v1-surge-l2-r02.parquet` | 1,851,688 | 324,125 | `ffd4efcdad963061ba0a301629b489bef1d025b276e28bfec1cad77a7bede382` |
| `logs/lv1_linux-v1-surge-l2-r03.parquet` | 1,866,079 | 324,057 | `fe4d9d35446d5636d9ff97f1c488763f7cb08afd064a5dc19962b1081c43d6b9` |
| `logs/lv1_linux-v1-surge-l3-r01.parquet` | 2,031,137 | 365,595 | `00e630fc920c21947fc3af379092515ce05dc49c296ee30a72f5e00b5160203d` |
| `logs/lv1_linux-v1-surge-l3-r02.parquet` | 2,012,314 | 365,594 | `119cc8490a3fdd5643675299c30696e77182e2e753159245644d437a796b9246` |
| `logs/lv1_linux-v1-surge-l3-r03.parquet` | 1,998,259 | 365,523 | `d90d6bc253174956ae76ae3976c3baf8acb47d357e50d800cef8905c579466c5` |

</details>
