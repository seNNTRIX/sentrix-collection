# Mac 로컬 대시보드 데모

팀의 Linux 학습/장애 실험과 별개인, `sentrix-core`·`sentrix-dashboard` 실제 연동용 구성이다.
기존 `deploy/online-boutique`를 재사용하고 맥에서 필요한 시작 대기와 .NET 호환 설정만 덧씌운다.

## 데이터 흐름

```text
브라우저 / k6 → Online Boutique
                   ├─ OTLP traces → OTel Collector → span metrics ─┐
                   └─ 컨테이너 자원·Deployment 정보 ────────────────┤
                                                    Prometheus ←─┘
                                                        ↓ 조회
                                               Spring Boot → 대시보드
```

MySQL에는 환경·연결 설정이 저장된다. 시계열 메트릭은 Prometheus에 저장한다.
이 구성은 메트릭 화면 검증용이다. 원본 로그·트레이스 저장, 장애 주입, RCA는 포함하지 않는다.
Prometheus 보관 기간은 1시간이고 저장소는 임시 볼륨이다. Pod를 교체하면 과거 지표가 사라질 수 있다.

## 필요한 도구와 버전

- Docker Desktop, kubectl, k3d 5.9.0, Helm 3.17.3, 선택적으로 k6 0.57.0
- k3s `v1.33.4-k3s1`
- Prometheus chart `29.30.0`
- OTel Collector chart `0.173.1`, Collector `0.160.0`
- Online Boutique `v0.9.0` (기존 팀 배포 파일과 동일)

2026-10-28에 Apple Silicon / 호스트 8 GiB / Docker 약 4 GiB에서 실행했다.
다른 프로젝트의 서버와 동시에 실행할 여유는 부족하다. 다른 프로젝트 중지는 소유자 확인 후 별도로 처리한다.
Intel용 Boutique 이미지가 에뮬레이션되므로 이 맥의 응답시간은 Linux 학습 환경의 성능 기준이 아니다.

아래 명령은 이 저장소 루트에서 실행한다. 도구가 PATH에 있어야 한다.
이번 세션의 도구는 `/private/tmp/sentrix-tools`에 받았으며 OS가 임시 파일을 지우면 다시 설치해야 한다.

## 최초 실행

```sh
k3d cluster create sentrix-local \
  --image rancher/k3s:v1.33.4-k3s1 --servers 1 --agents 0 --no-lb \
  --api-port 127.0.0.1:6550 \
  --kubeconfig-update-default=false --kubeconfig-switch-context=false \
  --k3s-arg '--disable=traefik,servicelb,metrics-server@server:0' --timeout 180s
mkdir -p /private/tmp/sentrix-local
k3d kubeconfig get sentrix-local > /private/tmp/sentrix-local/kubeconfig
chmod 600 /private/tmp/sentrix-local/kubeconfig
export KUBECONFIG=/private/tmp/sentrix-local/kubeconfig
kubectl create namespace sentrix
kubectl apply -k deploy/local-demo

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm upgrade --install prometheus prometheus-community/prometheus \
  --version 29.30.0 -n sentrix \
  -f deploy/prometheus/values-minimal.yaml -f deploy/local-demo/prometheus-values.yaml \
  --wait --timeout 5m
helm upgrade --install otel-gateway open-telemetry/opentelemetry-collector \
  --version 0.173.1 -n sentrix -f deploy/local-demo/otel-values.yaml \
  --wait --timeout 5m
kubectl wait --for=condition=Available deployment --all -n sentrix --timeout=300s
```

각각 별도 터미널에서 유지한다. Pod가 교체되면 port-forward를 다시 실행한다.

```sh
kubectl --kubeconfig /private/tmp/sentrix-local/kubeconfig -n sentrix port-forward --address 127.0.0.1 svc/frontend 8088:80
```

```sh
kubectl --kubeconfig /private/tmp/sentrix-local/kubeconfig -n sentrix port-forward --address 127.0.0.1 svc/prometheus-server 9090:80
```

## 백엔드와 화면 연결

1. sentrix-core MySQL 및 Java 서버를 실행한다. 서버의 `SENTRIX_DATASOURCE_ALLOWED_URLS`에 `http://127.0.0.1:9090`이 있어야 한다.
2. 대시보드에서 namespace가 `sentrix`인 환경을 선택한다.
3. 데이터 소스 설정에서 Prometheus 주소 `http://127.0.0.1:9090`, 제한 시간 5초를 저장하고 연결 검사한다.
4. 서비스별 개요에서 `frontend`와 `지난 5분`을 선택한다. 자동 갱신은 `30초마다 새로고침`으로 켠다.
5. `http://127.0.0.1:8088`에서 쇼핑하거나 아래 요청 생성을 실행한다.

```sh
BASE_URL=http://127.0.0.1:8088 TARGET_RPS=0.2 DURATION=15m \
  PRE_ALLOCATED_VUS=1 MAX_VUS=2 STAGE_TIMEOUT=15s \
  RUN_ID=local-dashboard-demo PROFILE_NAME=local-demo \
  k6 run workload/k6/browse-cart-checkout.js
```

5초마다 한 쇼핑 흐름을 실행한다. 한 흐름은 여러 HTTP 요청을 포함하며 15분 후 자동 종료된다.
집계와 수집에 시간이 필요하므로 시작 후 약 1~2분 뒤 지표를 확인한다.
현재 구간의 빈 값은 0으로 채우지 않는다. 트래픽이 없으면 응답시간·오류 비율 계산값이 없을 수 있다.

## 수집 계약과 범위

- CPU·메모리: cAdvisor, Pod→ReplicaSet→Deployment 연결: kube-state-metrics.
- 요청 수: `traces_span_metrics_calls_total`, 응답시간: `traces_span_metrics_duration_milliseconds_bucket`.
- `service_name`, `service_namespace="sentrix"`, `span_kind="SPAN_KIND_SERVER"`로 조회한다.
- 수집기의 단위를 `ms`로 고정한다. legacyMetricNames 기능은 켜지 않는다(지표 이름의 접두사가 사라짐).
- 이 gateway는 **sentrix 한 환경 전용**이다. v0.9 Node.js 서비스가 누락하는 `service.namespace`만 `sentrix`로 보충한다. 여러 환경을 한 수집기로 받을 때는 실제 Kubernetes namespace를 식별하도록 변경해야 한다.
- 요청 지표 대상: frontend, checkoutservice, productcatalogservice, recommendationservice, currencyservice, paymentservice, emailservice.
- adservice, cartservice, shippingservice, redis-cart에는 현재 OTLP 계측이 없으므로 CPU·메모리만 기대한다.
- 서비스 목록은 namespace의 모든 Deployment다. 관측 도구 3개와 실행을 중지한 loadgenerator도 목록에 포함된다. 목록 등재 자체는 정상 실행을 뜻하지 않는다.
- 시작 검사는 최대 5분 동안 기다린다. 정상 동작 후의 상태 검사는 유지한다.
- 장바구니의 `DOTNET_EnableWriteXorExecute=0`은 [.NET Rosetta 호환 이슈](https://github.com/dotnet/runtime/issues/106819)에 대한 로컬 설정이다.

## 중지와 다시 시작

요청 생성과 port-forward 터미널은 Ctrl+C로 끝낸다. 클러스터 전체는 다음처럼 중지/재개하며 MySQL은 별개다.

```sh
k3d cluster stop sentrix-local
k3d cluster start sentrix-local
```

재개한 후 위의 port-forward 두 개, Java 서버, 대시보드, 필요한 요청 생성을 다시 실행한다.
클러스터 삭제나 Docker 볼륨 삭제는 중지에 필요하지 않다.

## 실제 검증 기록 — 2026-10-28

- 맥 전용 설정 적용 후 쇼핑몰 11개 + 관측 도구 3개 Pod 모두 Ready, 해당 쇼핑몰 Pod 재시작 0회 확인.
- MySQL 약 506 MiB, Kubernetes 노드 약 1.74 GiB 사용 확인(당시 스냅샷).
- 환경 1의 Prometheus 연결 검사 `CONNECTED`, 실제 Deployment 15개 조회.
- Java API 실제 조회 57건: 계측한 7개 서비스 × 7종 지표 + 나머지 4개 × CPU·메모리. 모두 유효한 값 확인.
- 정상 쇼핑 흐름 53회 연속 성공 확인: 홈페이지·상품·장바구니 추가·장바구니 확인·주문 완료. 이는 로컬 정상 연동 검사이며 부하 한계나 장애 탐지 성능 평가는 아니다.
- Chrome에서 API를 가로채거나 가짜 응답을 넣지 않고 frontend의 그래프 7개, paymentservice 전환, 저장된 연결 상태 확인.
- 수집기 재설정 전의 조회 구간은 `PARTIAL`로 나타날 수 있다. 실제로 수집하지 않은 과거 값을 보충하지 않았다.
- SentriX 화면의 JavaScript 오류는 없었다. 원본 Boutique 화면에서는 외부 Bootstrap 스크립트가 jQuery의 `fn`을 찾지 못하는 오류 2건이 남아 있다. 홈페이지와 서버 주문 흐름은 확인했지만, 원본 쇼핑몰의 모든 브라우저 상호작용은 검증하지 않았다.
- 재시작을 포함한 장시간 안정성, 장애 주입, RCA 판정은 아직 검증 범위가 아니다.

이번 세션에서 사용한 로컬 주소:

| 대상 | 주소 |
| --- | --- |
| SentriX 대시보드 | http://127.0.0.1:5175/#B5-Service?service=frontend |
| Java API | http://127.0.0.1:8080 |
| Online Boutique | http://127.0.0.1:8088 |
| Prometheus | http://127.0.0.1:9090 |
