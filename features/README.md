# features/

window·라벨·feature 계산 라이브러리. 연구(RE2-OB, linux-v1)와 실시간 시스템(sentrix-core)이 **같은 코드**를 쓴다.

구조 원칙:

- 데이터 원천별 **adapter**(RE2-OB, linux-v1)가 case 하나를 공통 long format(시각, 서비스, 지표 이름, 값)으로 바꾼다.
- 그 뒤의 window 분할, 라벨, feature 계산은 원천과 무관한 공통 코드다.
- window: 30초, 10초 간격(`campaigns/linux-v1/feature-schema.yaml`과 같게). window 안 실제 표본 수와 mask를 함께 기록한다.
- 모델 입력 금지 항목은 `feature-schema.yaml`의 `forbidden_features`를 따른다(서비스 이름, case ID, 절대 시각, 장애 시각 등).
- feature마다 이름, 단위, 계산식, 입력 원천을 `CATALOG.md`에 적는다(R2에서 작성).

진행 계획: `docs/RE2OB-DEVELOPMENT-GUIDE.md` R2.
