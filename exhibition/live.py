"""Fixed-scope fault experiments on the local Online Boutique cluster."""
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# Exhibition targets with server request metrics and their direct application calls.
EDGES = {
    "frontend": ["productcatalogservice","currencyservice","recommendationservice","checkoutservice"],
    "checkoutservice": ["productcatalogservice","paymentservice","emailservice","currencyservice"],
    "recommendationservice": ["productcatalogservice"],
}
SERVICES = sorted(set(EDGES).union(*EDGES.values()))
KINDS = {"network_delay":"NetworkChaos","packet_loss":"NetworkChaos","cpu_saturation":"StressChaos","pod_failure":"PodChaos"}
PREFIX = "/apis/chaos-mesh.org/v1alpha1/namespaces/sentrix/"
OWNER = "sentrix-exhibit"
PORT = int(os.environ.get("SENTRIX_EXHIBIT_PORT", "5190"))
AUTHORITY = f"127.0.0.1:{PORT}"
DASHBOARD = f"http://{AUTHORITY}/display"
CORE = "http://127.0.0.1:8080/api/v1/environments/1"
DURATION = 180
# Fixed operator-selected profiles; the model never receives the fault or target.
LOSS_PERCENT = 15
PROFILES = {
    "network_delay": {"condition": "지연 100 ms · 지터 10 ms", "source": "frontend", "target": "productcatalogservice"},
    "packet_loss": {"condition": f"손실률 {LOSS_PERCENT}%", "source": "recommendationservice", "target": "productcatalogservice"},
    "cpu_saturation": {"condition": "CPU 작업자 1개 · 부하 100%", "source": "", "target": "productcatalogservice"},
    "pod_failure": {"condition": "Pod 1개 중단", "source": "", "target": "paymentservice"},
}


def build(fault, source, target, run):
    if fault not in KINDS or target not in SERVICES:
        raise ValueError("지원하지 않는 대상입니다.")
    def selector(name):
        return {"namespaces":["sentrix"], "labelSelectors":{"app":name}}
    spec = {"mode":"one","duration":f"{DURATION}s"}
    if fault in ("network_delay","packet_loss"):
        if target not in EDGES.get(source, []):
            raise ValueError("쇼핑몰에 정의된 호출 경로를 선택하세요.")
        # At source egress, kube-proxy may not have translated the service
        # address to its pod IP yet. Include the selected in-cluster service.
        spec.update(selector=selector(source), direction="to", target={"mode":"one","selector":selector(target)},
                    externalTargets=[f"{target}.sentrix.svc.cluster.local"])
        if fault=="network_delay":
            spec.update(action="delay",delay={"latency":"100ms","jitter":"10ms"})
        else:
            spec.update(action="loss",loss={"loss":str(LOSS_PERCENT)})
    else:
        if source: raise ValueError("서비스 실험에는 호출 출발지가 없습니다.")
        spec["selector"]=selector(target)
        if fault=="cpu_saturation":
            spec["stressors"]={"cpu":{"workers":1,"load":100}}
        else:
            spec["action"]="pod-failure"
    return {"apiVersion":"chaos-mesh.org/v1alpha1","kind":KINDS[fault],
            "metadata":{"namespace":"sentrix","name":"sx-"+run,"labels":{"app.kubernetes.io/managed-by":OWNER}},
            "spec":spec}


def kube(*args, body=None):
    service_cfg = os.environ.get("SENTRIX_EXHIBIT_SERVICE_KUBECONFIG")
    if service_cfg:
        identity = ["--kubeconfig", service_cfg]
    else:
        cfg = os.environ.get("SENTRIX_EXHIBIT_KUBECONFIG", "/private/tmp/sentrix-local/kubeconfig")
        identity = ["--kubeconfig", cfg, "--context=k3d-sentrix-local",
                    "--as=system:serviceaccount:sentrix:sentrix-exhibit"]
    command = ["kubectl", *identity, "--namespace=sentrix", "--request-timeout=35s", *args]
    p=subprocess.run(command,input=json.dumps(body) if body else None,capture_output=True,text=True,timeout=42)
    if p.returncode: raise RuntimeError("실험 클러스터 응답을 확인할 수 없습니다.")
    return json.loads(p.stdout)


def injection(obj):
    status=obj.get("status",{})
    exp=status.get("experiment",{})
    conditions={x["type"] for x in status.get("conditions",[]) if x["status"]=="True"}
    events=[e for record in exp.get("containerRecords",[]) for e in record.get("events",[]) if e["type"]=="Succeeded"]
    applied=max((e["timestamp"] for e in events if e["operation"]=="Apply"),default=None)
    recovered=min((e["timestamp"] for e in events if e["operation"]=="Recover"),default=None)
    stopped=exp.get("desiredPhase")=="Stop" or "Paused" in conditions
    done=stopped and "AllRecovered" in conditions
    return applied,recovered,done


def active_experiments():
    def items(kind):
        return kube("get","--raw="+PREFIX+kind.lower()+"?labelSelector=app.kubernetes.io%2Fmanaged-by%3D"+OWNER)["items"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        return [x for group in pool.map(items,sorted(set(KINDS.values()))) for x in group if not injection(x)[2]]


def timestamp(s):
    return datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()


def model_observation(windows, applied, recovered, baseline, api, location, rank):
    start = timestamp(applied)
    stop = timestamp(recovered) if recovered else time.time()
    baseline_end = timestamp(baseline["windowEnd"])
    version = baseline["modelVersion"]
    rows = sorted((w for w in windows if w.get("modelVersion") == version),
                  key=lambda w: (timestamp(w["windowEnd"]), w.get("createdAt", ""), w["jobId"]))
    before = next((w for w in reversed(rows) if w.get("decision") and baseline_end <= timestamp(w["windowEnd"]) <= start), baseline)
    update = {"before": before["decision"], "beforeJob": before["jobId"], "beforeWindow": before["windowEnd"]}
    overlapping = [w for w in rows if w.get("status") == "SUCCEEDED" and w.get("decision")
                   and timestamp(w["windowEnd"]) > start and timestamp(w["windowStart"]) < stop]
    # Both 30-second model windows are fully exposed when the earlier one (10 s back) starts after Apply.
    full = [w for w in overlapping if timestamp(w["windowStart"]) - 10 >= start and timestamp(w["windowEnd"]) <= stop]
    # An older job may still finish first in model-window order.
    pending = [timestamp(w["windowEnd"]) for w in rows
               if w.get("status") in ("QUEUED", "RUNNING") and timestamp(w["windowEnd"]) > baseline_end]
    checked_incidents = set()
    for alarm in overlapping:
        incident = alarm.get("incidentId")
        if alarm["decision"] != "ANOMALY" or not incident or incident in checked_incidents:
            continue
        if pending and min(pending) <= timestamp(alarm["windowEnd"]):
            break
        checked_incidents.add(incident)
        opening = api(f"{CORE}/incidents/{incident}/rca?at=first")
        result = opening.get("result")
        if not result:
            break
        if opening["incidentId"] != incident or result["decision"] != "ANOMALY":
            raise ValueError("첫 경보 응답 불일치")
        if timestamp(result["windowEnd"]) <= start:
            full = [w for w in full if w.get("incidentId") != incident]
            continue  # This incident was already underway before Apply.
        if result["jobId"] != alarm["jobId"] or timestamp(result["windowEnd"]) != timestamp(alarm["windowEnd"]):
            break  # The first-result and scheduler reads straddled a completion; poll again.
        if result["modelVersion"] != version:
            break
        job = result["jobId"]
        full = [w for w in full if timestamp(w["windowEnd"]) <= timestamp(alarm["windowEnd"])]
        update.update(decision="ANOMALY", reason=alarm.get("reason"), score=result["score"], candidates=result["candidates"],
                      locationRank=rank(result["candidates"], location), job=job, window=result["windowEnd"],
                      detected=alarm.get("finishedAt"), partialWindow=alarm not in full,
                      link=f"{DASHBOARD}#B4-Incident?incidentId={incident}&jobId={job}")
        break
    if "job" not in update:
        # Only a verified opening result can establish an anomaly for this run.
        full = [w for w in full if w["decision"] != "ANOMALY"]
    if full or "job" in update:
        if "job" not in update:
            last = full[-1]
            update.update(decision=last["decision"], reason=last.get("reason"), window=last["windowEnd"])
        update.update(windowsChecked=len(full), normalWindows=sum(w["decision"]=="NORMAL" for w in full),
                      abstainedWindows=sum(w["decision"]=="ABSTAIN" for w in full),
                      anomalyWindows=sum(w["decision"]=="ANOMALY" for w in full))
    return update


def observe(manifest, api, update, rank):
    fault=manifest["kind"].lower()
    name=manifest["metadata"]["name"]
    path=PREFIX+fault+"/"+name
    location=manifest["spec"]["selector"]["labelSelectors"]["app"]
    if fault=="networkchaos":
        location+="->"+manifest["spec"]["target"]["selector"]["labelSelectors"]["app"]
    update(step="클러스터 확인 중")
    if active_experiments():
        raise ValueError("다른 실험이 아직 종료되지 않았습니다. 클러스터 복구 뒤 다시 시도하세요.")
    # Fail before injection if the regular observation scheduler is off.
    settings=api(CORE+"/monitoring")
    if not settings.get("enabled") or settings.get("executionStatus")!="SCHEDULED":
        raise ValueError("SentriX 설정에서 환경의 자동 분석을 먼저 활성화하세요.")
    update(step="주입 전 정상 판정 확인 중")
    overview = api(CORE + "/overview?limit=8")
    recent = overview["recentWindows"]
    baseline = next((w for w in recent if w.get("status") not in ("QUEUED", "RUNNING")), None)
    if not baseline or not 0 <= time.time()-timestamp(baseline["windowEnd"]) <= 120:
        raise ValueError("최근 2분의 모델 판정이 없습니다. 자동 분석이 재개된 뒤 다시 시작하세요.")
    update(before=baseline.get("decision"), beforeJob=baseline["jobId"], beforeWindow=baseline["windowEnd"])
    if baseline.get("status") != "SUCCEEDED" or baseline.get("decision") != "NORMAL" or overview["openIncidents"]:
        raise ValueError("최근 모델 판정이 정상이고 진행 중인 장애가 모두 종료된 뒤 새 실험을 시작하세요.")
    update(step="실험 생성 중")
    try:
        kube("create","--raw="+PREFIX+fault+"?fieldValidation=Strict","-f","-",body=manifest)
    except (RuntimeError,subprocess.TimeoutExpired):
        # A lost create response can still mean the experiment was accepted.
        # Read the same unique run; never start a second experiment as a retry.
        try:
            kube("get","--raw="+path)
        except (RuntimeError,subprocess.TimeoutExpired) as error:
            raise RuntimeError("클러스터에서 이번 주입 요청의 접수를 확인하지 못했습니다.") from error
    update(created=True,step="주입 확인 중")
    started=time.monotonic()
    found=False
    while time.monotonic()-started < DURATION+240:
        try:
            obj=kube("get","--raw="+path)
            applied,recovered,done=injection(obj)
        except (OSError,RuntimeError,subprocess.TimeoutExpired):
            update(step="클러스터 상태 조회 재시도 중")
            time.sleep(5)
            continue
        update(applied=applied,recovered=recovered,step="주입 종료" if done else "주입됨" if applied else "주입 확인 중")
        if applied and not found:
            try:
                windows=api(CORE+"/anomaly-scores?limit=50")
                observation = model_observation(windows, applied, recovered, baseline, api, location, rank)
                update(**observation)
                found = bool(observation.get("job"))
            except (OSError,ValueError,KeyError):
                update(step="모델 결과 조회 재시도 중")
        if done and (not applied or found or (recovered and time.time()-timestamp(recovered)>90)):
            update(phase="done",step="실험 종료" if applied else "주입 미확인")
            return
        time.sleep(5)
    raise ValueError("상태 확인 시간이 지났습니다. 주입·제거 여부는 클러스터 기록을 확인하세요.")
