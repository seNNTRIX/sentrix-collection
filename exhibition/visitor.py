"""Two local exhibition screens. Submits recorded windows to the existing Java analysis API."""
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
LABELS = {"network_delay": "네트워크 지연", "pod_failure": "결제 Pod 중단",
          "cpu_saturation": "CPU 포화", "packet_loss": "패킷 손실"}
CASES = {x["fault"]: x for x in json.loads((DEMO / "demo-times-b-fold2.json").read_text())}
lock = threading.Lock()
state = {"phase": "idle"}


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
                     "service": "frontend", "title": "Online Boutique · 실험 구간 재분석",
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
        if self.path == "/state":
            with lock:
                payload = json.dumps(state, ensure_ascii=False).encode()
            return self.send(200,"application/json; charset=utf-8",payload)
        if self.path in ("/", "/display"):
            return self.send(200,"text/html; charset=utf-8",(HERE/"screens.html").read_bytes())
        return self.send_error(404)

    def do_POST(self):
        if self.path!="/start": return self.send_error(404)
        if self.headers.get("Origin")!=ORIGIN or self.headers.get("Host")!="127.0.0.1:5190":
            return self.send_error(403)
        if self.headers.get_content_type()!="application/json": return self.send_error(415)
        try:
            length=int(self.headers["Content-Length"])
            if not 0<length<=160: raise ValueError()
            selection=json.loads(self.rfile.read(length))["case"]
            if selection not in CASES: raise ValueError()
        except (KeyError,ValueError,TypeError):
            return self.send_error(400)
        with lock:
            if state["phase"]=="running": return self.send_error(409)
            run=str(uuid.uuid4())
            state.clear()
            state.update(phase="running",run=run,label=LABELS[selection])
        threading.Thread(target=analyze,args=(selection,run),daemon=True).start()
        self.send(202,"application/json",b'{"accepted":true}')


if __name__=="__main__":
    ThreadingHTTPServer(("127.0.0.1",5190),Handler).serve_forever()
