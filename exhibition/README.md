# 졸업전시 두 화면

맥북과 큰 모니터를 확장 모드로 연결한다. 이 페이지는 같은 맥에서 실행하는 전시 도구다. 쇼핑몰에서 이전에 기록한 장애 실험의 관측 특징을 사용한다. 버튼을 누를 때마다 Java가 새 분석 작업을 만들고 Python 모델의 응답을 MySQL에 저장한다. 운영 대시보드에는 주입 버튼이 없다.

| 화면 | 주소 | 역할 |
|---|---|---|
| 관람객 | http://127.0.0.1:5190/ | 기록된 실험 네 종류 중 하나 선택 |
| 큰 모니터 | http://127.0.0.1:5190/display | 실제 재생 환경의 SentriX 화면을 띄우고 방금 완료한 작업과 원인 후보를 표시 |

## 실행

전시 맥의 기존 MySQL 컨테이너, JDK 21, 모델 가상환경, 대시보드 빌드와 Java JAR가 필요하다. 이 저장소와 sentrix-core, sentrix-dashboard, sentrix-model-server는 같은 상위 폴더에 둔다. `exhibition/start.sh`를 실행한다. 서버가 이미 떠 있으면 재사용한다. 새 전시 DB를 준비할 때는 sentrix-core의 기존 Linux 실험 재생 설정으로 환경을 먼저 등록한다. 일반 제품과 관람객용 전시는 별도 DB를 사용한다.

## 관람객에게 설명할 때

“실제 Online Boutique에서 기록한 장애 실험을 선택해 주세요. 모델이 그때의 관측 자료를 지금 다시 분석하고, 조사할 서비스나 호출 경로를 순서대로 보여 줍니다.”

전시 모델은 linuxv1-b-fold2이며 네 사례는 학습에서 제외한 반복 2의 실험이다. 파일 선택은 팀의 `demo-times-b-fold2.json`에 기록된 장애 중 시각을 따른다. 버튼의 유형은 실험자가 알고 있는 정답이다. 모델 요청에는 환경·시각·버전·작업 식별자가 들어간다. 모델 출력은 정상·이상·보류 판정과 원인 위치 후보이며 세부 장애 유형을 분류하지 않는다. 한 사례의 순위로 전체 성능을 설명하지 않는다.

연구에서 장애 주입 도구와 진단 알고리즘을 구분한 사례는 [OSDI의 FIRM 실험](https://www.usenix.org/system/files/osdi20-qiu.pdf)에 나온다. 제품 시연에서 시나리오 선택과 진단 화면을 전환하는 예로는 [Dynatrace의 Astronomy Shop 데모](https://www.dynatrace.com/news/blog/opentelemetry-demo-application-with-dynatrace/)가 있다. 이 전시의 저장 기록 재분석은 맥북 운영 조건에 맞춘 선택이다.
