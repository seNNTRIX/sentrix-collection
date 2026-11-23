# SentriX 전시 콘솔

맥북에는 [실험 설정](http://127.0.0.1:5190/), 확장 디스플레이에는 [관측 대시보드](http://127.0.0.1:5190/display)를 연다. 전시 도구만 실험을 요청한다. 제품 대시보드는 환경의 지표와 독립적인 모델 결과를 보여 준다.

| 방식 | 대상 | 큰 화면 |
|---|---|---|
| 실시간 실험 | Online Boutique 배포 설정의 11개 서비스와 15개 단방향 호출. CPU·Pod 실험은 서비스 하나, 지연·손실은 출발과 도착을 선택한다. | Java가 반환한 최근 5분의 서비스 지표와 운영 대시보드. 네트워크 실험의 실시간 그래프는 출발 서비스 전체의 지표다. |
| 기록 재생 | 실험 기록이 있는 유형·위치 조합만 선택한다. | 저장된 30초 구간들을 원래 시간축에서 8배속으로 보여 준다. 경로는 호출 p90, 서비스는 기준 기간 대비 CPU 변화다. 지정한 구간의 새 분석 결과는 별도 재생 DB에서 열린다. |

그래프의 빈칸은 관측 표본이 없는 구간이다. 실시간 주입과 복구는 클러스터가 돌려준 이벤트 시각, 이상 감지는 분석 작업의 실제 종료 시각으로 표시한다. 재생의 ‘분석 구간 끝’은 기록 시각이다. 모델이 정상이나 보류를 반환하면 그 판정을 표시한다. 주입한 위치와 후보 순위는 추론 후에 비교한다. 선택한 장애 유형은 실험 조건이고 모델은 원인 위치를 순위로 반환한다.

## 맥북에서 실행

1. 기존 전시 환경에서 쇼핑몰과 관측 DB, Java, 모델 서버와 대시보드를 실행한다. 실시간 연결은 대시보드 5176, Java 8080, 환경 1을 사용한다. 해당 환경의 자동 분석을 켠다.
2. 실시간 실험에는 로컬 k3d-sentrix-local 클러스터의 Chaos Mesh와 sentrix 네임스페이스의 전시 계정이 필요하다. 권한 정의는 operator-rbac.yaml이다. 실험 하나의 지속 시간은 180초다. 다른 실험이 복구되기 전에는 다음 실험을 시작할 수 없다.
3. 이 저장소와 sentrix-core, sentrix-dashboard, sentrix-model-server를 같은 폴더에 둔다. exhibition/start.sh를 실행한다. 재생 서버는 별도 포트(5177, 8081, 8001)에서 실행한다.
4. 사이트 점검은 python3 -m unittest discover -s exhibition 으로 한다.

실험 동작과 대상을 따로 고르는 인터페이스는 [AWS FIS의 실험 구성](https://docs.aws.amazon.com/fis/latest/userguide/experiment-templates.html)을 참고했다. 실험 설정 후 별도 관측 화면에서 요청을 조사하는 흐름은 [Dynatrace의 OpenTelemetry 데모](https://www.dynatrace.com/news/blog/opentelemetry-demo-application-with-dynatrace/)에 나온다.
