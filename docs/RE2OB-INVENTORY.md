# RE2-OB 구조 조사 (R1)

조사일: 2026-10-27 · 브랜치 `research-re2ob` · 계획: `docs/RE2OB-DEVELOPMENT-GUIDE.md` R1
이 문서의 내용은 **내려받은 파일을 직접 읽어 확인한 것**과 **공식 자료에서 인용한 것**만 담는다. 확인하지 못한 것은 "미확인"으로 적는다.

## 1. 출처와 무결성

| 항목 | 값 |
|---|---|
| 출처 | Zenodo record 14590730, `RE2-OB.zip` (RCAEval `download_re2ob_dataset()`과 같은 URL) |
| 크기 | 1,191,025,569 bytes (압축), 8.66 GB (해제) |
| md5 | `b9e23f8842c404b396ffd2becff15de4` — Zenodo API 공개값과 일치 |
| sha256 | `0605a36cdcad8a6ae0107f2357c9c91ecee2c4ab5d72579bffea0372d9747513` |
| 위치 | `data/RE2/RE2-OB/` (git 제외), 체크섬 `data/RE2/CHECKSUMS.txt` |
| 압축 해제 | 항목 1,214개, 절대경로·`..` 경로 없음 확인 후 해제 |

`docs/RE2_SCHEMA.md`는 Hugging Face parquet 배포본 1개 case를 보고 쓴 문서다. **Zenodo 배포본은 파일 구성이 다르다**(아래 3절). 이후 작업은 이 Zenodo 배포본을 기준으로 한다.

## 2. case 구성

- 폴더 규칙: `RE2-OB/<서비스>_<장애>/<반복 번호>/`. 반복 번호는 `1`, `2`, `3`.
- **유효 case 90개** = 서비스 5 × 장애 6 × 반복 3. 셀 30개 모두 반복 3개.
- **예외 폴더 1개:** `checkoutservice_cpu/multi-source-data/`. 파일 구성이 다르고(`.DS_Store` 포함, `simple_metrics.csv` 없음, 지표 열 73개), RCAEval의 multi-source 예제 데이터로 보인다. **case에서 제외한다.**

| 대상 서비스 (5) | 장애 표기 (6) |
|---|---|
| checkoutservice, currencyservice, emailservice, productcatalogservice, recommendationservice | `cpu`, `mem`, `disk`, `delay`, `loss`, `socket` |

**linux-v1과 대상 서비스가 하나 다르다.** RE2-OB는 `emailservice`, linux-v1은 `paymentservice`를 쓴다. 겹치는 대상은 checkout·currency·productcatalog·recommendation 4개다.

## 3. case 폴더의 파일

| 파일 | 형식 | 내용 |
|---|---|---|
| `inject_time.txt` | 정수 한 줄 | 장애 주입 시각, Unix 초 (예: `1705354566`) |
| `metrics.csv` | 넓은 표, 1초 간격 | `time` + `<대상>_<지표>` 열 402~462개 (case마다 다름). 원천 카운터 그대로(누적값 포함) |
| `simple_metrics.csv` | 넓은 표, 1초 간격 | `time` + `<서비스>_<지표>` 약 70~74열. RCAEval이 정리한 간단 지표 |
| `logs.csv` | 줄 단위 | `time`(HH:MM), `timestamp`(Unix **나노초**), `container_name`, `message`, `level`, `req_path`, `error`, `cluster_id`, `log_template` (일부 case는 7열) |
| `cluster_info.json` | JSON | 로그 템플릿 번호 → 템플릿 문장, 해당 컨테이너 |
| `logts.csv` | 넓은 표, **15초 간격** | 로그 템플릿별 개수 시계열 (`<컨테이너>_<템플릿 번호>`) |
| `traces.csv` | span 단위 | `time`, `traceID`, `spanID`, `parentSpanID`, `serviceName`, `methodName`, `operationName`, `startTimeMillis`(ms), `startTime`(µs), `duration`(**µs**), `statusCode`(실수, 예 `0.0`) |
| `tracets_lat.csv`, `tracets_err.csv` | 넓은 표, **15초 간격** | `<서비스>_<메서드>`별 지연·오류 시계열 (17개 작업) |
| `pod-node-1.csv`, `pod-node-2.csv` | `POD, NODE_NAME` | Pod가 배치된 노드 |
| `metrics_postprocess.log` | 텍스트 | 지표 후처리 로그 (일부 열 길이 1440/1441 경고 등) |

### 크기 (90 case 합계)

| 파일 | 합계 | case당 중앙값 |
|---|---|---|
| `traces.csv` | 6.37 GB | 약 39.8만 span |
| `logs.csv` | 1.56 GB | 약 17.5만 줄 |
| `metrics.csv` | 0.61 GB | 1,441행 |
| `simple_metrics.csv` | 0.11 GB | 1,441행 |
| 15초 시계열 3종 | 무시할 수준 | 97행 |

`traces.csv`가 대부분이라, R2에서는 trace를 case 단위로 나눠 읽거나 필요한 열만 읽어야 한다.

## 4. 지표

### `simple_metrics.csv`의 지표 종류

`cpu`, `mem`, `socket`, `workload`, `latency-50`, `latency-90`, `diskio`(일부 서비스만), `error`(오류가 있었던 서비스만).

### `metrics.csv`의 지표 종류 (58종)

- 컨테이너(cAdvisor): `container-cpu-usage-seconds-total`, `container-cpu-system/user-seconds-total`, `container-spec-cpu-quota`, `container-memory-*`(working-set, rss, cache, usage 등), `container-network-receive/transmit-*`(packets, bytes, dropped, errors), `container-fs-*`, `container-blkio-*`, `container-sockets`
- **Istio**: `istio-request-total`, `istio-error-total`, `istio-latency-50/90/95/99`, `istio-bytes-*`
- 노드: `node-cpu-seconds-total`, `node-memory-*`, `node-disk-*`, `node-network-*` (GKE 노드 이름으로 열이 붙음)

**linux-v1과의 차이:** RE2-OB는 Istio 서비스 메시와 GKE 다중 노드에서 수집됐다. linux-v1은 Istio 없이 OTel spanmetrics로 호출률·오류·지연을 만들고, 단일 노드 k3s다. 그래서 `istio-*` 지표와 노드 지표는 공통 feature가 될 수 없다. 공통으로 쓸 수 있는 것은 컨테이너 CPU·메모리·네트워크와, trace에서 계산하는 호출 지연·오류다.

### 측정 간격과 시간 구간

| 항목 | 값 |
|---|---|
| 지표 간격 | 1초 (모든 행 간격 1.0초 확인) |
| 장애 전 길이 | 90 case 모두 720초 |
| 장애 후 길이 | 88 case 720초. 2 case는 짧음(209초, 283초) |
| 시각이 빈 행 | `checkoutservice_cpu/2` 256행, `checkoutservice_mem/2` 258행 (지표 열 길이 불일치로 보임) |
| 15초 시계열 | 장애 시각보다 약 726초 앞에서 시작, 97행 |
| **장애 종료 시각** | **파일에 없음 (미확인).** 장애 후 720초 전체가 장애 지속 구간인지, 중간에 제거됐는지는 데이터만으로 알 수 없다 |

R2 라벨 규칙: 장애 시각 이전 720초 = 정상, 이후 = 장애 구간으로 둔다. 종료 시각이 없으므로 "회복" 라벨은 만들지 않는다. 장애 직후의 전환 구간을 얼마나 뺄지는 R2에서 정하고 근거를 적는다.

## 5. 서비스 이름 대응 (`identity/service-alias-map.yaml` 기준)

현재 alias map은 canonical 이름 11개만 있고 별칭은 없다(`aliases: {}`).

| RE2-OB에 나오는 이름 | 나오는 곳 | canonical 대응 | 판단 |
|---|---|---|---|
| `frontendservice` | `traces.csv`의 `serviceName`, `tracets_*.csv` 열 | `frontend` | **별칭 필요** |
| `frontend-external` | 지표 열(`_workload`, `_error`, `istio-request/error-total`) | 대응 없음 | 외부 진입 지점(Ingress 측 Istio 지표). 서비스 노드가 아니라 입구 지표로 별도 처리 |
| `redis` | 지표 열, `logs.csv`의 `container_name` | `redis-cart` | **별칭 필요** |
| `loadgenerator` | 지표 열 | 대응 없음 | 부하 발생기. 후보에서 제외 |
| `traceservice`, `health` | `tracets_*.csv` 열 (`traceservice_Export`, `health_Check`) | 대응 없음 | 계측·헬스체크 호출. 후보에서 제외 |
| `gke-gke-cluster-default-pool-…` | 노드 지표 열 | 대응 없음 | 노드. 서비스 후보가 아님 |
| 나머지 10개 서비스 이름 | 지표·로그·trace | 같은 이름 | 그대로 대응 |

trace에는 계측된 7개 서비스만 나온다(frontendservice, checkout, currency, productcatalog, recommendation, payment, email). linux-v1과 같다.

alias map은 수집 코드도 쓰므로 이 단계에서는 고치지 않았다. R2의 RE2-OB adapter에서 위 대응을 적용하고, alias map 반영 여부는 따로 결정한다.

## 6. 평가 지표 정의 (RCAEval 논문)

출처: Pham et al., *RCAEval: A Benchmark for Root Cause Analysis of Microservice Systems with Telemetry Data*, arXiv 2412.17015 v5, 4.2절 "Evaluation Metrics".

- 장애 case 집합 A, case a에 대해 방법이 낸 순위 `R^a`(0부터 셈), 실제 원인 집합 `V^a_rc`.
- **AC@k** = (1/|A|) · Σ_{a∈A} [ Σ_{i<k} 𝟙(R^a[i] ∈ V^a_rc) ] / min(k, |V^a_rc|)
  - 상위 k개 안에 실제 원인이 들어 있는 비율. RE2는 case마다 원인이 1개이므로, 원인이 상위 k등 안에 있으면 1, 아니면 0을 case 평균한 값과 같다.
- **Avg@k** = (1/k) · Σ_{j=1..k} AC@j
- 논문은 AC@1, AC@3, Avg@5를 보고한다.

### RE2-OB 기준 결과

**미확인.** 논문의 RE2 결과표(Table 6)는 Train Ticket(RE2-TT)만 싣고 있다. RCAEval README에도 RE2-OB 수치가 없다. README에 있는 실행 예시는 `python main.py --method baro --dataset re2-tt` 형태이고, RE2-OB용으로 `--dataset re2-ob`가 있다. **R3에서 RCAEval 코드로 BARO 등을 직접 돌려 비교 기준값을 만든다.**

참고(다른 시스템): Table 6, RE2-TT 평균 Avg@5 — BARO 0.80(지표), 0.81(multi-source).

## 7. R2 이후에 영향을 주는 결정 사항

1. 예외 폴더 `multi-source-data` 제외, 유효 case 90개.
2. 짧은 case 2개(`checkoutservice_cpu/2`, `checkoutservice_mem/2`)는 시각이 빈 행을 버리고 쓰되, R2 표에 표시한다.
3. 지표 원천: 1차는 `simple_metrics.csv`(정리된 지표), 필요한 경우 `metrics.csv`의 컨테이너 지표를 rate로 변환해 추가. Istio·노드 지표는 linux-v1에 없으므로 공통 feature에서 제외(RE2-OB 전용 실험으로만).
4. 1초 지표를 30초 window로 묶으면 window당 표본 30개(linux-v1은 5초 scrape라 6개). 표본 수 차이를 mask·표본 수 열로 기록한다.
5. trace는 µs 단위 duration, `frontendservice` → `frontend` 대응.
6. 비교 가능한 대상: 공통 4개 서비스(checkout, currency, productcatalog, recommendation)와 공통 장애 3종(cpu, delay, loss).

## 8. 재현 방법

```bash
bash rcaeval/download_re2.sh OB          # 또는 Zenodo에서 직접 받고 md5 대조
python -I rcaeval/inventory_re2.py data/RE2 --out rcaeval/out
```

`rcaeval/out/`(git 제외)에 `cases.csv`, `files.csv`, `summary.md`가 생긴다. 이 문서의 세부 수치(예외 폴더, 시간 구간, 이름 목록)는 별도의 읽기 전용 분석으로 확인했다.
