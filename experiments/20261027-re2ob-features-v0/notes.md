# RE2-OB feature v0 build

- 90 case, fold 1/2/3 각 30 case. 빌드 45분(4 프로세스), 결과 22 MB.
- ranking 표: 61,336행(장애 활성 window × 후보 11개), 정답 행 5,576개, feature 67개.
- detection 표: 9,176행(정상 3,600 + 장애 활성 5,576), feature 58개.
- 짧은 case 2개: `checkoutservice_cpu_2`(장애 후 205초, 장애 window 12개), `checkoutservice_mem_2`(280초, 20개). 제외하지 않고 표시만 함.
- 원인 서비스에 지표·trace가 없는 case는 없음.
- 결측 50% 넘는 feature: `f_ct_out_*`, `f_ct_in_edge_p90_lr`(호출하는 쪽/받는 연결이 있는 서비스만 값이 있음), `f_opt_in_p99_lr`(span 100개 미만이면 NaN). 구조적 결측이라 정상.
- 탐지 표는 정상:장애 = 3,600:5,576. RE2-OB의 장애 구간(12분)이 정상 구간(학습용 7분)보다 길기 때문. R3/R4에서 case 단위 평가 구간(+60~300초)을 쓰면 비율이 달라진다.
