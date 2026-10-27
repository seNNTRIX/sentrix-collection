# evaluation/

평가 지표와 case 단위 평가 규칙.

- 원인 순위: AC@1, AC@3, Avg@5(RCAEval 논문 정의대로, R1에서 확인), MRR.
- 탐지: AUROC, AUPRC.
- 신뢰구간: case 단위 bootstrap. window 단위 bootstrap은 쓰지 않는다.
- window 점수를 case 하나의 순위로 합치는 규칙은 R3에서 정하고, 이후 성능을 보고 바꾸지 않는다.

진행 계획: `docs/RE2OB-DEVELOPMENT-GUIDE.md` R3.
