# 클라우드 세션 인수인계 (2026-10-27)

로컬 데스크톱 세션("SentriX 최종 프로젝트 컨텍스트", 2026-10-16 시작)에서 클라우드로 옮기며 남긴 메모다.
대화 전체가 아니라 요약만 넘어가므로, 이어서 일할 때 필요한 사실과 결정을 여기에 모았다.

## 이 폴더의 파일

| 파일 | 내용 |
|---|---|
| `RE2-OB-개발-가이드.md` | RE2-OB로 feature·모델을 미리 개발하는 작업 설명과 단계별 프롬프트(R0~R5) |
| `면담-진행상황-20261020.md` | 10/20 면담용 진행 상황 메모 |
| `포스터-초안.md` | 포스터 문안 초안 |
| `SentriX-poster*.html` | 포스터 시안 v1~v5 (v5가 최신: UI 영역을 APM 화면 두 장으로 교체) |

면담 발표 자료(슬라이드 12장)는 claude.ai artifact로 있다: https://claude.ai/artifact/NJ1AgTTaGbPsEYHXUwmazN

## 브랜치 지도 (github.com/seNNTRIX/sentrix-collection, 공개 저장소)

| 브랜치 | 내용 |
|---|---|
| `school-pc` | 학교 실습 PC(206-40)의 정식 수집 진행. **수집 상태는 이 브랜치 최신 커밋과 `docs/SETUP-REVIEW-20261016.md` 7절이 기준** |
| `research-re2ob` | RE2-OB 개발 결과. R5 방법 고정(`METHOD-FREEZE.md`, 고정 커밋 해시 기록) |
| `docs-context-20261019` | 프로젝트 컨텍스트 재작성(10/19). 이 브랜치(`cloud-handoff`)의 기준 |
| `collect-206-39` | 다른 실습 PC(206-39) 수집 브랜치 |
| `main` | 10/16 최초 셋업 스냅샷 |

## 지금까지 확정된 결정

- **대상 앱은 Online Boutique 하나.** 개발 데이터(RE2-OB), 직접 수집(linux-v1), 최종 데모 모두. Sock Shop/EKS 계획은 폐기.
- **데이터 역할:** linux-v1 69 pair = 학습·평가(반복 기준 3-fold)·데모 모델의 주 데이터. RE2-OB = feature·모델 설정을 미리 고정하는 개발용 + 비교 실험.
- **수집은 원래 계획(69 pair / 138 run, matched control)** 유지. 빠른 수집안(연속 에피소드 5시간)은 채택하지 않음.
- **실행 순서:** Tier 1(cpu·delay·loss 45) → Tier 2(pod_failure 15) → Tier 3(traffic_surge 9). 공용 PC라 하루 블록 단위로 실행하고 끊기면 재개.
- **처리 용량 C = 6 tx/s** (rate 8에서 p99 545 ms로 FAIL). 평소 부하 0.4C = 2.4 tx/s.
- **delay·loss 주입 경로 수정:** 서비스가 Service ClusterIP로 호출해서 Pod IP 대상 NetworkChaos가 걸리지 않았음. ClusterIP를 대상에 추가하는 방법(방법 A)으로 해결.
- 리허설 실측: pair당 약 96분, 약 5.2 GiB.

## 작업 방식

- 학교 PC에는 그 PC의 Claude Code 세션이 있고, 사용자가 그 보고를 붙여 넣으면 이쪽에서 **단계별 프롬프트를 하나씩** 만들어 준다(한 번에 전부 주지 않음).
- 학교 PC 에이전트 규칙: 단계마다 멈추고 보고, sudo는 사용자가 직접 실행, run ID 재사용·덮어쓰기 금지, 판정 기준을 결과에 맞춰 바꾸지 않음, 단계마다 `school-pc`에 commit·push.
- RE2-OB 연구는 사용자의 다른 컴퓨터에서 `research-re2ob` 브랜치로 진행.
- 사용자에게는 쉬운 한국어로, 표와 단계로 설명한다.

## 최근 상태 (로컬 fork 세션 보고 기준, 확인은 각 브랜치에서)

- 206-40 수집이 블록 단위로 진행 중. surge의 incident record 생성 오류(workload_entrypoint 미지원)는 수정되어 재실행됨.
- RE2-OB 결과: 최종 방법(변화량 feature LightGBM 순위 + 통계 방법 순위 평균) Avg@5 = 0.981(학습 때 본 서비스), 0.959(처음 보는 서비스).
