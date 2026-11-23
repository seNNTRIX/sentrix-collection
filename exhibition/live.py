"""Fixed-scope fault experiments on the local Online Boutique cluster."""
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# Direct application dependencies specified by deploy/online-boutique/manifest-original.yaml.
EDGES = {
    "frontend": ["productcatalogservice","currencyservice","cartservice","recommendationservice","shippingservice","checkoutservice","adservice"],
    "checkoutservice": ["productcatalogservice","shippingservice","paymentservice","emailservice","currencyservice","cartservice"],
    "recommendationservice": ["productcatalogservice"],
    "cartservice": ["redis-cart"],
}
SERVICES = sorted(set(EDGES).union(*EDGES.values()))
KINDS = {"network_delay":"NetworkChaos","packet_loss":"NetworkChaos","cpu_saturation":"StressChaos","pod_failure":"PodChaos"}
PREFIX = "/apis/chaos-mesh.org/v1alpha1/namespaces/sentrix/"
OWNER = "sentrix-exhibit"
DASHBOARD = "http://127.0.0.1:5176"
CORE = "http://127.0.0.1:8080/api/v1/environments/1"
DURATION = 180


def build(fault, source, target, run):
    if fault not in KINDS or target not in SERVICES:
        raise ValueError("지원하지 않는 대상입니다.")
    def selector(name):
        return {"namespaces":["sentrix"], "labelSelectors":{"app":name}}
    spec = {"mode":"one","duration":f"{DURATION}s"}
    if fault in ("network_delay","packet_loss"):
        if target not in EDGES.get(source, []):
            raise ValueError("쇼핑몰에 정의된 호출 경로를 선택하세요.")
        spec.update(selector=selector(source),direction="to",target={"mode":"one","selector":selector(target)})
        if fault=="network_delay":
            spec.update(action="delay",delay={"latency":"100ms","jitter":"10ms"})
        else:
            spec.update(action="loss",loss={"loss":"2"})
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
    cfg=os.environ.get("SENTRIX_EXHIBIT_KUBECONFIG","/private/tmp/sentrix-local/kubeconfig")
    command=["kubectl","--kubeconfig",cfg,"--context=k3d-sentrix-local","--namespace=sentrix",
             "--as=system:serviceaccount:sentrix:sentrix-exhibit","--request-timeout=35s",*args]
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
    update(step="실험 생성 중")
    kube("create","--raw="+PREFIX+fault+"?fieldValidation=Strict","-f","-",body=manifest)
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
                previous=next((w for w in windows if w.get("decision") and timestamp(w["windowEnd"])<=timestamp(applied) and timestamp(w["windowEnd"])>=timestamp(applied)-180),None)
                if previous: update(before=previous["decision"])
                limit=timestamp(recovered) if recovered else time.time()
                eligible=sorted((w for w in windows if w.get("decision") and timestamp(w["windowStart"])>=timestamp(applied)+10 and timestamp(w["windowEnd"])<=limit),key=lambda w:w["windowEnd"])
                if eligible:
                    last=eligible[-1]
                    update(decision=last["decision"],reason=last.get("reason"),window=last["windowEnd"])
                alarm=next((w for w in eligible if w.get("decision")=="ANOMALY" and w.get("incidentId")),None)
                if alarm:
                    i,j=alarm["incidentId"],alarm["jobId"]
                    result=api(f"{CORE}/incidents/{i}/rca-jobs/{j}/result")
                    if result["jobId"]!=j or result["decision"]!="ANOMALY": raise ValueError("판정 응답 불일치")
                    update(decision="ANOMALY",score=result["score"],candidates=result["candidates"],
                           locationRank=rank(result["candidates"],location),job=j,window=result["windowEnd"],detected=alarm.get("finishedAt"),
                           link=f"{DASHBOARD}/#B4-Incident?incidentId={i}&jobId={j}")
                    found=True
            except (OSError,ValueError,KeyError):
                update(step="모델 결과 조회 재시도 중")
        if done and (not applied or found or (recovered and time.time()-timestamp(recovered)>90)):
            update(phase="done",step="실험 종료" if applied else "주입 미확인")
            return
        time.sleep(5)
    raise ValueError("상태 확인 시간이 지났습니다. 주입·제거 여부는 클러스터 기록을 확인하세요.")
