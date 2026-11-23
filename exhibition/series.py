"""Wall chart data. All timestamps are epoch seconds on the observation clock."""
import json
from datetime import datetime, timezone
from urllib.parse import urlencode
import time

from live import CORE, timestamp

STEP = 10
SPAN = 300


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def live_series(state, api):
    location = state.get("location", "frontend")
    service = location.split("->")[0]
    fault = state.get("fault")
    metric, label, unit = {
        "cpu_saturation": ("cpu_usage_cores", "CPU 사용량", "cores"),
        "pod_failure": ("error_ratio", "서비스 오류율", "%"),
        "packet_loss": ("error_ratio", "서비스 오류율", "%"),
    }.get(fault, ("latency_p90_ms", "서비스 응답 시간 p90", "ms"))
    end = int(time.time()) // STEP * STEP
    query = urlencode({"service":service, "metric":metric, "from":iso(end-SPAN),
                       "to":iso(end+1), "stepSeconds":STEP})
    data = api(CORE+"/metrics?"+query)
    if data["service"] != service or data["metric"] != metric or data["environmentId"] != 1:
        raise ValueError("다른 지표 응답")
    factor = 100 if unit == "%" else 1
    points = [[timestamp(p["timestamp"]), None if p["value"] is None else p["value"] * factor]
              for p in data["points"]]
    return {"title":label, "subject":service, "unit":unit, "points":points,"end":end,
            "step":STEP,"span":SPAN}


def replay_series(state, cases, demo):
    case = cases[state["fault"]]
    manifest = json.loads((demo/"replay-cases.json").read_text())
    experiment = next(x for x in manifest["cases"] if x["case_id"] == case["case_id"])
    start = int(timestamp(experiment["first_window_end"]))
    end = int(timestamp(experiment["last_window_end"]))
    location = case["root_cause"]
    edge = "->" in location
    points = []
    for t in range(start,end+1,STEP):
        path = demo/"replay"/"1"/(str(t)+".json")
        value = None
        if path.is_file():
            record = json.loads(path.read_text())
            if record["namespace"] != "sentrix" or timestamp(record["windowEnd"]) != t:
                raise ValueError("실험 구간 불일치")
            features = record["features"]
            if edge:
                match = next((e for e in features["edges"] if e["source"]+"->"+e["target"]==location),None)
                if match and match.get("p90") is not None and match["calls"]>0:
                    value = match["p90"]*1000
            else:
                value = features["nodes"].get(location,{}).get("f_cm_cpu_cores_dmean")
        points.append([t,value])
    return {"title":"호출 경로 p90" if edge else "CPU 평균 사용량 변화",
            "subject":location,"unit":"ms" if edge else "평소 변동폭 단위",
            "points":points,"step":STEP,"span":SPAN,"start":start,"end":end,
            "onset":experiment["onset_unix"],"removal":experiment["removal_unix"]}
