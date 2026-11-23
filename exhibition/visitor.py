"""Local exhibition console and wall display."""
import subprocess
import live
import series
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
DEMO = HERE.parents[1] / "sentrix-model-server" / "demo"
DASH = "http://127.0.0.1:5177"
ROOT = DASH + "/api/v1/environments"
ORIGIN = "http://127.0.0.1:5190"
ENV_NAME = "실제 실험 기록 재생 · Linux Online Boutique 반복 2"
MODEL = "linuxv1-b-fold2"
LABELS = {"network_delay": "네트워크 지연", "pod_failure": "Pod 중단",
          "cpu_saturation": "CPU 포화", "packet_loss": "패킷 손실"}
def recorded_cases():
    path = DEMO / "demo-times-b-fold2.json"
    return {x["fault"]: x for x in json.loads(path.read_text())} if path.is_file() else {}


CASES = recorded_cases()
lock = threading.Lock()
state = {"phase": "idle", "mode": "live"}


def api(url, body=None):
    post = None if body is None else json.dumps(body).encode()
    with urlopen(Request(url, data=post, headers={"Content-Type": "application/json"}), timeout=12) as response:
        return json.load(response)


def update(**fields):
    with lock:
        state.update(fields)


def location_rank(candidates, target):
    """Compare only after inference; an edge must match both endpoints in order."""
    for item in candidates:
        location = (item["source"] + "->" + item["target"] if item["kind"] == "EDGE"
                    else item["service"])
        if location == target:
            return item["rank"]
    return None


def analyze(selection, run):
    case = CASES[selection]
    try:
        health = api("http://127.0.0.1:8001/health")
        expected = json.loads((DEMO / "model-b-fold2/calibration.json").read_text())
        if (health.get("onlineFeatureStatus"), health.get("modelVersion"), health.get("threshold")) != (
                "FILE_INPUT_ONLY", MODEL, expected["threshold"]):
            raise ValueError("전시용 모델과 기준값을 확인해 주세요.")
        envs = api(ROOT)["items"]
        if len(envs) != 1 or (envs[0]["id"], envs[0]["name"], envs[0]["namespace"]) != (1, ENV_NAME, "sentrix"):
            raise ValueError("저장 실험 전용 환경을 확인해 주세요.")
        end = case["during"]["windowEnd_unix"]
        stamp = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
        # One case record, a fresh inference job for every visitor. No fault labels in the model request.
        record = api(ROOT + "/1/incidents", {"requestKey": str(uuid.uuid5(uuid.NAMESPACE_URL,"exhibition-v1/"+case["case_id"])),
                     "service": "frontend", "title": "실험 구간 재분석",
                     "occurredAt": stamp(end-30), "description": "전시용 재분석 기록. 서비스 필드는 쇼핑몰 진입점입니다. 실제 원인 후보는 아래 모델 결과에 표시됩니다."})
        jobs = ROOT + "/1/incidents/" + record["id"] + "/rca-jobs"
        job = api(jobs, {"requestKey": run, "windowEnd": stamp(end)})
        job_id = job["id"]
        link = DASH + "/#B4-Incident?incidentId=" + record["id"] + "&jobId=" + job_id
        url = jobs + "/" + job_id
        update(window=stamp(end), job=job_id)
        deadline = time.monotonic() + 120
        while job["status"] in ("QUEUED", "RUNNING") and time.monotonic() < deadline:
            time.sleep(0.5)
            job = api(url)
        if job["status"] != "SUCCEEDED":
            raise ValueError("분석 작업 상태 · "+job["status"])
        result = api(url + "/result")
        if (result["jobId"] != job_id or result["modelVersion"] != MODEL or
                datetime.fromisoformat(result["windowEnd"].replace("Z","+00:00")).timestamp() != end):
            raise ValueError("선택한 분석 구간과 결과가 일치하지 않습니다.")
        update(phase="done", link=link, decision=result["decision"], score=result["score"],
               candidates=result["candidates"], reason=result.get("abstainReason"),
               locationRank=location_rank(result["candidates"],case["root_cause"]))
    except (HTTPError, URLError, TimeoutError, KeyError, ValueError, OSError) as exc:
        update(phase="failed", message=str(exc) if isinstance(exc,ValueError) else "재생용 Java·모델 서버의 연결과 작업 상태를 확인하세요.")


def selection(payload, run):
    if not isinstance(payload, dict) or set(payload) != {"mode", "case", "source", "target"}:
        raise ValueError("실험 조건을 선택하세요.")
    mode, fault, source, target = (payload[k] for k in ("mode","case","source","target"))
    if not all(isinstance(x,str) for x in (mode,fault,source,target)) or mode not in ("live","replay"):
        raise ValueError("잘못된 실험 조건입니다.")
    manifest = live.build(fault, source, target, run)
    location = source + "->" + target if source else target
    if mode == "replay" and CASES.get(fault, {}).get("root_cause") != location:
        raise ValueError("선택한 조합의 기록이 없습니다.")
    return manifest, location


def run_live(manifest):
    try:
        live.observe(manifest, api, update, location_rank)
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired, KeyError) as exc:
        update(phase="failed", message=str(exc) if isinstance(exc,(RuntimeError,ValueError)) else "클러스터 또는 관측 서버 응답을 확인하세요.")


class Handler(BaseHTTPRequestHandler):
    def send(self, status, mime, data):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.headers.get("Host") != "127.0.0.1:5190":
            return self.send_error(403)
        if self.path == "/series":
            with lock:
                snapshot = state.copy()
            try:
                if snapshot["mode"] == "replay":
                    data = series.replay_series(snapshot, CASES, DEMO)
                else:
                    data = series.live_series(snapshot, api)
            except (ValueError, OSError, KeyError, StopIteration):
                return self.send(503,"application/json",b'{"unavailable":true}')
            return self.send(200,"application/json",json.dumps(dict(data,run=snapshot.get("run"),mode=snapshot["mode"]),allow_nan=False).encode())
        if self.path == "/catalog":
            catalog = {"services":live.SERVICES, "edges":live.EDGES,
                       "recordings":{k:v["root_cause"] for k,v in CASES.items()}}
            return self.send(200,"application/json",json.dumps(catalog).encode())
        if self.path == "/state":
            with lock:
                payload = json.dumps(state, ensure_ascii=False).encode()
            return self.send(200,"application/json; charset=utf-8",payload)
        if self.path == "/chart.js":
            return self.send(200,"application/javascript; charset=utf-8",(HERE/"chart.js").read_bytes())
        if self.path in ("/", "/display"):
            return self.send(200,"text/html; charset=utf-8",(HERE/"screens.html").read_bytes())
        return self.send_error(404)

    def do_POST(self):
        if self.path != "/start": return self.send_error(404)
        if self.headers.get("Origin")!=ORIGIN or self.headers.get("Host")!="127.0.0.1:5190":
            return self.send_error(403)
        if self.headers.get_content_type()!="application/json": return self.send_error(415)
        run = str(uuid.uuid4())
        try:
            length = int(self.headers.get("Content-Length","0"))
            if not 0 < length <= 400: raise ValueError("요청 크기가 잘못되었습니다.")
            payload = json.loads(self.rfile.read(length))
            manifest, location = selection(payload, run)
        except (ValueError, TypeError) as exc:
            return self.send(400,"text/plain; charset=utf-8",str(exc).encode())
        mode, fault = payload["mode"], payload["case"]
        with lock:
            if state["phase"]=="running": return self.send_error(409)
            state.clear()
            state.update(phase="running", mode=mode, run=run, label=LABELS[fault],
                         location=location, fault=fault, step="요청 접수", started=datetime.now(timezone.utc).isoformat())
        if mode == "live":
            worker = threading.Thread(target=run_live, args=(manifest,), daemon=True)
        else:
            worker = threading.Thread(target=analyze, args=(fault,run), daemon=True)
        worker.start()
        self.send(202,"application/json",b'{"accepted":true}')


if __name__=="__main__":
    ThreadingHTTPServer(("127.0.0.1",5190),Handler).serve_forever()
