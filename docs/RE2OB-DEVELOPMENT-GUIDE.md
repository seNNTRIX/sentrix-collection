# RE2-OB로 feature·모델 미리 개발하기 — 설명과 단계별 프롬프트

작성: 2026-10-20
대상: SentriX 졸업작품 (Online Boutique RCA)
실행 위치: **집 컴퓨터의 Claude Code** (학교 PC는 정식 수집 전용으로 둔다)

---

## 1. 이 작업이 무엇인가

학교 PC가 정식 수집(69 pair, 약 3주)을 혼자 도는 동안, 공개 데이터 **RCAEval RE2-OB**로 다음을 미리 정해 두는 작업이다.

- 모델에 넣을 **입력(feature)** 이 무엇인지
- 어떤 **모델**과 **설정값(하이퍼파라미터)** 을 쓸지
- 성능을 어떻게 **평가**할지 (평가 코드 포함)

수집이 끝나면, 여기서 고정한 방법을 우리 데이터(linux-v1)에 **그대로** 적용해 학습·평가만 한다.

### 데이터별 역할

| 데이터 | 역할 |
|---|---|
| **linux-v1 (직접 수집 69 pair)** | 주 데이터. 3-fold 교차검증으로 학습·평가, 최종 데모 모델 학습 |
| **RE2-OB (공개 90 case)** | 방법 개발용. feature·모델·설정을 미리 정하고, 기존 논문 방법과 비교 |

### 왜 미리 하나

1. **시간:** 수집이 끝날 때까지 3주를 기다리지 않고, 끝나는 대로 결과를 낼 수 있다.
2. **공정한 평가:** 우리 데이터 결과를 보면서 feature나 설정을 바꾸면 "시험 문제를 보고 공부한" 셈이 된다. 공개 데이터로 미리 정하면 우리 데이터 결과를 믿을 수 있다.
3. **코드 재사용:** 여기서 만든 feature 계산 코드를 실시간 시스템(sentrix-core)과 데모에서 그대로 쓴다. 학습 때와 실제 사용 때 계산이 달라지는 문제를 막는다.

### RE2-OB에 대해 확인된 사실

RCAEval 공식 저장소(github.com/phamquiluan/RCAEval) 기준이다.

- Online Boutique, 90 case = 대상 서비스 5개 × 장애 6종(cpu, mem, disk, delay, loss, socket) × 반복 3회
- 지표(metrics), 로그, trace를 모두 제공
- 다운로드: Zenodo record 14590730의 `RE2-OB.zip`
- case 폴더에는 지표 파일과 `inject_time.txt`(장애 시각, Unix time), `logs.csv`, `traces.csv`가 있다. 정확한 파일 이름과 구조는 R1에서 직접 확인한다.
- AC@k, Avg@k의 **정확한 정의는 README에 없다.** 논문(arXiv 2412.17015)에서 확인해야 한다.

### 우리 데이터와의 관계

| | RE2-OB | linux-v1 |
|---|---|---|
| 앱 | Online Boutique | Online Boutique (같음) |
| 공통 장애 | cpu, delay, loss | cpu, delay, loss |
| RE2-OB에만 있음 | mem, disk, socket | — |
| linux-v1에만 있음 | — | pod_failure, traffic_surge |
| 정답 단위 | 서비스 | cpu·pod는 서비스, delay·loss는 서비스 간 연결 |
| 측정 간격 | R1에서 확인 | Prometheus 5초 |

### 3주 뒤 결과물

- RE2-OB 성능표: 기준 방법 vs 우리 모델, 데이터 조합별
- 고정된 feature 목록, 모델 종류, 설정값 문서
- linux-v1에 바로 적용할 수 있는 feature 계산·학습·평가 코드

---

## 2. 진행 방식

- 프롬프트는 **단계별로 하나씩** 붙여 넣는다. 에이전트가 단계 끝에 멈추면 결과를 확인하고 다음 단계를 준다.
- 작업은 같은 GitHub 저장소(`seNNTRIX/sentrix-collection`, 옛 `esther033/sentrix-final-v1`)의 **별도 브랜치 `research-re2ob`** 에서 한다. 학교 PC는 `school-pc` 브랜치에 push하므로 서로 부딪히지 않는다.
- 실험할 때마다 설정과 결과를 기록해서, 같은 실험을 다시 돌리면 같은 결과가 나오게 한다.

| 단계 | 내용 | 예상 시간 |
|---|---|---|
| R0 | 작업 환경 준비 | 30분 |
| R1 | RE2-OB 받기 + 구조 파악 + 평가 지표 정의 확인 | 반나절 |
| R2 | window·라벨·feature 파이프라인 | 1~2일 |
| R3 | 평가 코드 + 기준 방법 | 1일 |
| R4 | 학습 모델 + 비교 실험 | 3~5일 |
| R5 | 방법 고정 + linux-v1 적용 준비 | 반나절 |

컴퓨터 사양: GPU는 필요 없다. RAM 16 GB 이상, 디스크 여유 20 GB 이상이면 충분하다. trace 파일이 크면 R1에서 크기를 보고 읽는 방식을 정한다.

---

## 3. 단계별 프롬프트

### R0 — 작업 환경 준비

```text
SentriX 졸업작품의 연구 작업을 시작한다. 이 컴퓨터는 집 PC이고, 학교 PC는 정식 데이터 수집을 따로 진행 중이다.

목표: 공개 데이터 RCAEval RE2-OB로 feature·모델·평가 방법을 미리 개발하고 고정한다. 나중에 직접 수집한 linux-v1 데이터(69 pair)에 같은 방법을 그대로 적용한다.

먼저 할 일:
1. gh repo clone seNNTRIX/sentrix-collection 으로 받고, school-pc 브랜치를 기준으로 research-re2ob 브랜치를 만들어.
2. 다음 문서를 읽고 3~5줄로 요약해: docs/PROJECT-DIRECTION.md, campaigns/linux-v1/feature-schema.yaml, campaigns/linux-v1/label-schema.yaml, docs/RE2_SCHEMA.md.
3. Python 3.12 가상환경을 만들어 requirements.txt 를 설치하고 기존 테스트를 돌려. 연구용 패키지(scikit-learn, lightgbm 등)는 R3 이후 필요할 때 requirements-research.txt 에 버전을 고정해서 따로 관리해.
4. 새 코드는 다음 폴더에 둔다(없으면 만든다): features/ (feature 계산 라이브러리, 나중에 실시간 시스템과 공유), evaluation/ (지표 계산), experiments/ (실험 설정과 결과 기록), data/ (내려받은 데이터, git 제외).

작업 전체 규칙:
- 단계마다 결과를 보고하고 멈춰. 내가 지시하기 전에는 다음 단계로 넘어가지 마.
- 데이터셋 구조, 평가 지표 정의, 논문 결과 수치는 추측하지 말고 파일이나 공식 자료에서 확인한 것만 써. 확인 못 한 것은 "미확인"으로 표시해.
- 학습·평가는 항상 case 단위로 나눈다. 같은 case에서 나온 window가 학습과 평가에 동시에 들어가면 안 된다.
- scaler, feature 선택, 로그 템플릿 사전, 임계값은 학습 데이터로만 맞춘다.
- 서비스 이름, case ID, 절대 시각, 장애 시각처럼 정답을 흘리는 정보는 모델 입력에 넣지 마(feature-schema.yaml 의 forbidden_features 참고).
- 실험마다 experiments/<실험ID>/ 에 설정(데이터 버전, feature 버전, window 크기, 모델, 하이퍼파라미터, seed, 분할 방법)과 결과를 저장해.
- 단계가 끝나면 commit 하고 research-re2ob 브랜치로 push 해. data/ 와 큰 생성물은 올리지 마.
- 보고는 짧은 목록으로 써줘.

보고: 문서 요약, 테스트 결과, 만든 폴더, push 결과. 그리고 멈춰.
```

### R1 — RE2-OB 받기와 구조 파악

```text
R1: RE2-OB를 받고 구조를 사실대로 파악한다.

1. bash rcaeval/download_re2.sh OB 로 받아(디스크 여유를 먼저 확인). Zenodo가 느리면 재시도하고, 그래도 안 되면 RCAEval README에 있는 Hugging Face parquet 배포본을 대안으로 제안만 해.
2. python3 rcaeval/inventory_re2.py data/RE2 실행.
3. 결과로 다음을 답해(파일에서 확인한 것만):
   - case 수, 폴더 구조와 이름 규칙(서비스·장애·반복 번호가 어디에 있는지)
   - 대상 서비스 5개가 무엇인지, 장애 6종의 실제 표기
   - 지표 파일 형식, 컬럼 수, 컬럼 이름 패턴(서비스별 cpu/mem/latency/error 등), 측정 간격(초)
   - 로그·trace 파일의 컬럼과 크기
   - inject_time.txt 형식, 장애 전후 데이터 길이(초)
   - 장애가 끝난 시각 정보가 있는지
4. RCAEval 논문(https://arxiv.org/abs/2412.17015)에서 평가 지표 AC@1, AC@3, Avg@5의 정의를 찾아 수식과 함께 정리하고, 논문의 RE2-OB 결과표(방법별 수치)를 출처와 함께 기록해. 찾지 못한 것은 "미확인"으로.
5. RE2-OB와 linux-v1의 서비스 이름을 identity/service-alias-map.yaml 기준으로 대응시켜 보고, 맞지 않는 이름이 있으면 목록으로 보여줘.
6. 결과를 docs/RE2OB-INVENTORY.md 로 저장하고 commit, push.
보고 후 멈춰.
```

### R2 — window·라벨·feature 파이프라인

```text
R2: RE2-OB를 학습용 표로 바꾸는 파이프라인을 만든다. 같은 코드를 나중에 linux-v1 에도 쓸 것이므로, 데이터 원천별 "읽기" 부분과 공통 "feature 계산" 부분을 분리해.

1. 읽기(adapter): RE2-OB case 하나를 공통 long format(시각, 서비스, 지표 이름, 값)으로 바꾸는 코드. linux-v1 용 adapter는 자리만 만들고(인터페이스와 TODO), 실제 구현은 데이터가 생긴 뒤에 한다.
2. window: 30초 window, 10초 간격(feature-schema.yaml 과 같게). window 안의 실제 표본 수를 같이 기록하고, 표본이 부족하면 값 대신 null 과 mask.
3. 라벨: inject_time 이전 = 정상, 이후 = 장애. 장애 시각에 걸친 window 는 제외. 장애 구간 길이가 파일에 없으면 R1 결과를 근거로 규칙을 정하고 그 근거를 문서에 적어.
4. feature (처음엔 작게 시작한다. 늘리는 건 R4 실험으로 정한다):
   - 필수: 서비스별 지표의 평균·최대·표준편차, 장애 전 정상 구간 대비 변화량(정상 구간의 중앙값·IQR 로 정규화, 미래 데이터 사용 금지)
   - 선택: 기울기, 변화 시점, p90/p99
   - 실험용: trace 기반(서비스 간 호출 지연·오류), 로그 기반(오류 로그 수), 이웃 서비스 대비 상대 변화
   feature 마다 이름, 단위, 계산식, 입력 원천을 features/CATALOG.md 에 적어.
5. 출력 형식: 원인 순위 학습용 표(행 = case × window × 후보 서비스, 열 = feature + mask + 정답 여부)와 탐지용 표(행 = case × window).
6. case 단위 3-fold 분할: 반복 번호 기준(반복 1/2/3을 각 fold의 평가로). 분할 결과를 파일로 저장.
7. 테스트: 정답 정보(서비스 이름, case ID, 시각)가 feature 열에 들어가지 않는지 검사하는 테스트, 같은 case 가 두 fold 에 걸치지 않는지 검사하는 테스트를 반드시 추가.
보고: 표의 크기(행·열 수, case 수, fold별 개수), feature 목록, 결측 비율이 높은 feature, 테스트 결과. commit, push 후 멈춰.
```

### R3 — 평가 코드와 기준 방법

```text
R3: 평가 코드와 "넘어야 할 최소선"인 기준 방법을 만든다.

1. evaluation/ 에 지표 구현: R1에서 확인한 정의대로 AC@1, AC@3, Avg@5, 그리고 MRR. 탐지는 AUROC, AUPRC. 손으로 계산한 작은 예시로 단위 테스트.
2. case 단위 평가 규칙을 정해: window 별 점수를 case 하나의 순위로 합치는 방법(예: 장애 후 첫 N개 window 평균). 규칙은 이 단계에서 정하고, 이후 성능을 보고 바꾸지 마.
3. 기준 방법 3개:
   - 무작위 순위 (여러 seed 평균)
   - 통계 방법: 장애 전 정상 구간 대비 가장 크게 튄 서비스를 원인으로 지목 (RCAEval 의 BARO 와 같은 계열)
   - 가능하면 RCAEval 라이브러리의 기존 방법 1~2개를 그대로 돌려 비교값으로 기록(설치가 복잡하면 논문 수치만 인용하고 그렇다고 표시)
4. 결과는 장애 종류별(cpu, mem, disk, delay, loss, socket)로 나눠 보고하고, linux-v1 과 공통인 cpu·delay·loss 만 모은 값도 따로 계산해.
5. experiments/ 에 기록하고 commit, push.
보고: 방법별 성능표, 논문 수치와 비교(차이가 크면 원인 추정), 멈춰.
```

### R4 — 학습 모델과 비교 실험

```text
R4: 학습 모델을 만들고, 어떤 feature 가 실제로 도움이 되는지 실험한다.

1. 모델: GBDT(LightGBM 우선, 결정적 결과가 나오게 seed 고정)로 원인 후보 순위 모델과 탐지 모델을 만든다. 서비스 이름 없이 feature 만 보고 점수를 매기는 "공유 가중치" 방식으로(feature-schema.yaml 의 unseen_service_contract 참고).
2. 비교로 joint classification(서비스×장애 종류를 하나의 클래스로) baseline 도 하나 만들어 비교해.
3. 하이퍼파라미터는 학습 fold 안에서만 고르고(평가 fold 를 보고 고르지 마), 고르는 방법을 기록해.
4. 비교 실험 (모두 같은 분할·같은 평가 규칙):
   - feature 묶음: 필수만 / +선택 / +trace / +로그 / +이웃 대비 상대 변화
   - window 길이: 30초 기본, 60초 하나만 비교
   - 서비스 하나를 통째로 빼고 학습해서 그 서비스를 맞히는지 (일반화 확인)
5. 결과마다 fold 평균·표준편차, case 단위 bootstrap 신뢰구간을 보고. 차이가 신뢰구간 안이면 "차이 없음"으로 판단해.
6. feature 중요도 상위 15개와, 틀린 case 몇 개의 원인 분석(어떤 서비스로 잘못 지목했는지)을 정리해.
7. experiments/ 에 모두 기록하고 commit, push.
보고: 실험별 성능표, 이득이 확인된 feature 묶음, 이득이 없던 것, 오류 분석. 멈춰.
```

### R5 — 방법 고정과 linux-v1 적용 준비

```text
R5: 지금까지 결과로 최종 방법을 고정한다. 이 문서가 linux-v1 평가의 사전 계획서가 된다.

1. docs/METHOD-FREEZE.md 작성:
   - 최종 feature 목록(이름·계산식·입력 원천), window 설정, 정규화 방법
   - 모델 종류와 하이퍼파라미터 값, seed, 하이퍼파라미터를 고른 방법
   - case 단위 점수 합치는 규칙, 평가 지표와 보고 방식
   - RE2-OB 최종 성능과 기준 방법 대비 차이
   - linux-v1 에 적용할 때 바꾸면 안 되는 것과, 데이터 차이 때문에 조정이 필요한 것(측정 간격 차이, delay·loss 의 연결 단위 정답, pod_failure·traffic_surge 처럼 RE2-OB에 없는 장애)을 구분해서 적어.
2. linux-v1 adapter 의 인터페이스와 할 일 목록을 정리해. 실제 구현은 linux-v1 데이터가 나온 뒤에 한다.
3. 이 문서를 commit 할 때 커밋 해시를 문서 끝에 기록해(나중에 "미리 고정했다"는 증거).
4. push 하고 멈춰.
```

---

## 4. 주의할 점

- **RE2-OB 결과를 보고 우리 데이터 평가 방법을 정하는 건 괜찮지만, 그 반대는 안 된다.** linux-v1 결과를 보고 R5에서 고정한 방법을 바꾸면, 그 평가는 더 이상 공정하지 않다. 바꿔야 하면 바꾼 이유와 전후 결과를 둘 다 보고한다.
- **RE2-OB와 linux-v1은 장애 넣는 도구와 강도가 다르다.** RE2-OB에서 잘 되던 feature가 우리 데이터에서는 약할 수 있다. 그것도 그대로 보고할 결과다.
- **delay·loss의 정답 단위가 다르다.** RE2-OB는 서비스, 우리 데이터는 연결이다. 두 데이터를 같이 쓰는 실험에서는 대응 규칙(예: 연결 → 출발 서비스)을 미리 정하고, 그 규칙 때문에 생기는 쏠림(연결 5개 중 3개가 frontend 출발)을 같이 보고한다.
- 학교 PC 쪽 정식 수집 진행 상황과 섞이지 않게, 이 작업은 `research-re2ob` 브랜치에서만 한다.
