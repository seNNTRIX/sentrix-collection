"""Prepare an isolated observation clock for the ordinary 30-second Java worker."""
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(tempfile.gettempdir()) / "sentrix-exhibition-features"


def epoch(stamp):
    return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def cases(demo):
    path = demo / "replay-cases.json"
    if not path.is_file():
        return []
    return [c for c in json.loads(path.read_text())["cases"] if c["files_written"] > 0]


def prepare(demo, folder, case, now):
    folder.mkdir(mode=0o700, exist_ok=False)
    first = epoch(case["first_window_end"])
    last = epoch(case["last_window_end"])
    before_onset = math.ceil(case["onset_unix"]/30)*30-30
    offset = int(now)//10*10 - 30 - before_onset
    available = 0
    for end in range(first,last+1,10):
        source = demo / "replay" / "1" / f"{end}.json"
        if not source.is_file():
            continue
        doc = json.loads(source.read_text())
        if doc["namespace"] != "sentrix" or epoch(doc["windowEnd"]) != end or epoch(doc["windowStart"]) != end-30:
            raise ValueError("관측 파일의 시각 또는 환경이 일치하지 않습니다.")
        doc.update(windowStart=iso(end+offset-30), windowEnd=iso(end+offset))
        target = folder / f"{end+offset}.json"
        target.write_text(json.dumps(doc,allow_nan=False))
        available += 1
    if available != case["files_written"]:
        raise ValueError("실험 입력 파일 수가 일치하지 않습니다.")
    meta = {"case":case["case_id"],"offset":offset,"first":first,"last":last,"location":case["root_cause"]}
    (folder / "source.json").write_text(json.dumps(meta))
    return last+offset

def observation(folder, upto, service=None):
    """Only recorded windows already reached by the exhibition clock may be shown."""
    meta = json.loads((folder/"source.json").read_text())
    offset = meta["offset"]
    end = min(upto - 30, meta["last"] + offset)
    rows = []
    history = []
    for t in range(meta["first"] + offset, end+1,10):
        path = folder/f"{t}.json"
        features = json.loads(path.read_text())["features"] if path.is_file() else None
        edges = [e for e in features["edges"] if e["calls"]>0] if features else []
        if service is None:
            history.append({"time":iso(t),"cpu":{n:f.get("f_cm_cpu_cores_dmean") for n,f in features["nodes"].items()} if features else {},
                            "latency":{e["source"]+">"+e["target"]:1000*e["p90"] for e in edges if e.get("p90") is not None}})
            if t == end//10*10:
                return {"edges":edges,"nodes":sorted(features["nodes"]) if features else [],"history":history}
            continue
        outgoing = [e for e in edges if e["source"]==service]
        rate = sum(e["calls"] for e in outgoing)
        err = sum(e["err"]*e["calls"] for e in outgoing)/rate if rate and all(e["err"] is not None for e in outgoing) else None
        p90 = max((1000*e["p90"] for e in outgoing if e["p90"] is not None),default=None)
        rows.append({"timestamp":iso(t),"rate":rate if outgoing else None,"error":err,"p90":p90})
    return rows if service is not None else {"edges":[],"nodes":[]}
