"""Local exhibition console and wall display."""
import logging
import os
import subprocess
import tempfile
import live
import playback
import mimetypes
import re
from urllib.parse import urlsplit, parse_qs
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
DIST = HERE.parents[1] / "sentrix-dashboard" / "dist"
DASH = "http://127.0.0.1:8081"
ROOT = DASH + "/api/v1/environments"
ORIGIN = f"http://{live.AUTHORITY}"
ENV_NAME = "실제 실험 기록 재생 · Linux Online Boutique 반복 2"
MODEL = "linuxv1-b-fold2"
LABELS = {"network_delay": "네트워크 지연", "pod_failure": "Pod 중단",
          "cpu_saturation": "CPU 포화", "packet_loss": "패킷 손실"}
CASES = playback.cases(DEMO)
lock = threading.Lock()
state = {"phase": "idle", "mode": "live"}
state_file = None
pending_live_write = None


def restore_live(path):
    idle = {"phase":"idle", "mode":"live"}
    if path is None:
        return idle
    try:
        with path.open("rb") as src:
            data = src.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError("oversized run")
        saved = json.loads(data)
        if not isinstance(saved, dict) or saved.get("mode") != "live" or saved.get("phase") not in ("running","done","failed"):
            raise ValueError("invalid run")
        if not all(isinstance(saved.get(k), str) and saved[k] for k in ("run","started","fault","location")):
            raise ValueError("missing run identity")
        uuid.UUID(saved["run"])
        if saved["phase"] == "running":
            saved["phase"] = "failed"
            saved["message"] = "실험실 재시작으로 관측이 중단됐습니다. 표시된 결과는 재시작 전 마지막으로 확인한 값입니다."
        return saved
    except FileNotFoundError:
        return idle
    except (OSError, ValueError):
        logging.getLogger(__name__).warning("Could not read the last live run at %s", path)
        return idle


def write_live(path, current):
    if path is None or current.get("mode") != "live":
        return
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as fp:
            tmp = Path(fp.name)
            json.dump(current, fp, ensure_ascii=False, allow_nan=False)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)



def api(url, body=None, method=None):
    post = None if body is None else json.dumps(body).encode()
    with urlopen(Request(url, data=post, method=method, headers={"Content-Type": "application/json"}), timeout=12) as response:
        return json.load(response)


def checkpoint(current):
    """Called under lock. Keep the last live observation for a retry if storage is unavailable."""
    global pending_live_write
    if current.get("mode") != "live":
        return
    try:
        write_live(state_file, current)
        pending_live_write = None
    except (OSError, ValueError):
        if pending_live_write is None:
            logging.getLogger(__name__).exception("Could not save the latest live observation")
        pending_live_write = current.copy()


def update(**fields):
    with lock:
        if any(k not in state or state[k] != v for k,v in fields.items()):
            state.update(fields)
            checkpoint(state)


def location_rank(candidates, target):
    """Compare only after inference; an edge must match both endpoints in order."""
    for item in candidates:
        location = (item["source"] + "->" + item["target"] if item["kind"] == "EDGE"
                    else item["service"])
        if location == target:
            return item["rank"]
    return None


def monitor(env, enabled):
    return api(f"{ROOT}/{env}/monitoring", {"enabled":enabled, "intervalSeconds":30}, "PUT")


def analyze(case, run):
    env = None
    try:
        health = api("http://127.0.0.1:8001/health")
        expected=json.loads((DEMO/"model-b-fold2"/"calibration.json").read_text())
        if (health.get("onlineFeatureStatus"),health.get("modelVersion"),health.get("threshold")) != ("FILE_INPUT_ONLY",MODEL,expected["threshold"]):
            raise ValueError("전시 분석 서버 설정을 확인하세요.")
        if not (playback.ROOT/"1").is_dir() or not (playback.ROOT/"1").samefile(DEMO/"replay"/"1"):
            raise ValueError("전시 모델 서버를 최신 실행 설정으로 시작하세요.")
        if api(ROOT+"/1")["name"] != ENV_NAME:
            raise ValueError("전시 DB의 기준 환경을 확인하세요.")
        now = datetime.now().astimezone()
        item = api(ROOT, {"name":f"Online Boutique · 재현 {now:%m%d %H%M%S} {run[:4]}", "namespace":"sentrix"})
        env = item["id"]
        if env <= 1: raise ValueError("독립 실험 환경 생성 실패")
        last = playback.prepare(DEMO,playback.ROOT/str(env),case,time.time())
        (playback.ROOT/"active-environment").write_text(str(env))
        config = monitor(env,True)
        if config["executionStatus"] != "SCHEDULED": raise ValueError("자동 관측이 활성화되지 않았습니다.")
        update(environment={**item,"recorded":True}, step="관측 중")
        while time.time() <= last+120:
            rows = api(f"{ROOT}/{env}/anomaly-scores?limit=3")
            row = next((r for r in rows if r.get("decision")),None)
            if row:
                update(window=row["windowEnd"], decision=row["decision"], reason=row.get("reason"))
                if row.get("incidentId") and row["decision"]=="ANOMALY":
                    result=api(f"{ROOT}/{env}/incidents/{row['incidentId']}/rca-jobs/{row['jobId']}/result")
                    update(candidates=result["candidates"],locationRank=location_rank(result["candidates"],case["root_cause"]))
                else:
                    update(candidates=[], locationRank=None)
                if playback.epoch(row["windowEnd"]) >= last-29: break
            time.sleep(4)
        else:
            raise ValueError("마지막 구간의 분석을 확인하지 못했습니다.")
        update(step="실험 종료")
    except (OSError,ValueError,KeyError) as exc:
        update(message=str(exc) if isinstance(exc,ValueError) else "전시 서버 연결 또는 분석 작업을 확인하세요.")
    finally:
        if env is not None and env > 1:
            try:
                monitor(env,False)
                (playback.ROOT/"active-environment").unlink(missing_ok=True)
            except (OSError,ValueError): update(message="실험 환경의 자동 관측 중지를 확인하세요.")
        with lock:
            state.update(phase="failed" if state.get("message") else "done", ended=time.time())


def selection(payload, run):
    if not isinstance(payload, dict) or set(payload) != {"mode", "case", "source", "target"}:
        raise ValueError("실험 조건을 선택하세요.")
    mode, fault, source, target = (payload[k] for k in ("mode","case","source","target"))
    if not all(isinstance(x,str) for x in (mode,fault,source,target)) or mode not in ("live","replay"):
        raise ValueError("잘못된 실험 조건입니다.")
    manifest = live.build(fault, source, target, run)
    location = source + "->" + target if source else target
    if mode == "replay" and not any(c["fault"]==fault and c["root_cause"]==location for c in CASES):
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
        if self.headers.get("Host") != live.AUTHORITY:
            return self.send_error(403)
        path = urlsplit(self.path).path
        if path == "/display" or re.fullmatch(r"/assets/[A-Za-z0-9._-]+",path):
            file = DIST / ("index.html" if path=="/display" else path.lstrip("/"))
            if not file.is_file(): return self.send_error(404)
            return self.send(200,mimetypes.guess_type(file.name)[0] or "application/octet-stream",file.read_bytes())
        if path == "/display-policy":
            try:
                with urlopen("http://127.0.0.1:8000/health", timeout=3) as response:
                    health = json.load(response)
            except (OSError, ValueError):
                health = {}
            model_version = health.get("environmentModelVersions", {}).get("1", health.get("modelVersion"))
            return self.send(200, "application/json", json.dumps({"threshold": health.get("threshold"), "modelVersion": model_version, "applicationServices": live.SERVICES}).encode())
        if path == "/display-environment":
            with lock:
                env = state.get("environment")
                if state.get("ended",float("inf")) + 60 < time.time(): env=None
            pinned=parse_qs(urlsplit(self.path).query).get("environment",[])
            if pinned:
                if not re.fullmatch(r"[1-9][0-9]{0,15}",pinned[0]): return self.send_error(400)
                if pinned[0]=="1": env=None
                elif (playback.ROOT/pinned[0]/"source.json").is_file():
                    try: env={**api(ROOT+"/"+pinned[0]),"recorded":True}
                    except OSError: return self.send_error(503)
                else: return self.send_error(404)
            if not env:
                try: env=api(live.CORE)
                except OSError: return self.send_error(503)
            return self.send(200,"application/json",json.dumps(env).encode())
        if path.startswith("/api/v1/environments/") or path == "/actuator/health":
            match = re.fullmatch(r"/api/v1/environments/([1-9][0-9]*)(/.*)?",path)
            if match and match[1] != "1":
                if not (playback.ROOT/match[1]/"source.json").is_file(): return self.send_error(404)
                folder=playback.ROOT/match[1]
                query=parse_qs(urlsplit(self.path).query)
                if match[2] in ("/observed-calls","/observed-topology"):
                    try:
                        if match[2]=="/observed-calls":
                            service=query["service"][0]
                            if service not in live.SERVICES: raise ValueError()
                            value=playback.observation(folder,int(time.time()),service)
                        else:
                            end=playback.epoch(query["end"][0])
                            value=playback.observation(folder,min(int(time.time()),end+30))
                    except (KeyError,ValueError): return self.send_error(400)
                    return self.send(200,"application/json",json.dumps(value).encode())
                if match[2]=="/services":
                    value={"environmentId":int(match[1]),"items":[{"name":n,"kind":"Service"} for n in live.SERVICES]}
                    return self.send(200,"application/json",json.dumps(value).encode())
                base = DASH
            else:
                base = "http://127.0.0.1:8080"
            try:
                response=api(base+self.path)
            except HTTPError as exc:
                return self.send(exc.code,"application/json",exc.read())
            except OSError:
                return self.send_error(503)
            return self.send(200,"application/json",json.dumps(response).encode())
        if self.path == "/catalog":
            subjects = set(live.SERVICES) | {f"{src}->{dst}" for src,targets in live.EDGES.items() for dst in targets}
            catalog = {"services":live.SERVICES,"edges":live.EDGES,"profiles":live.PROFILES,"durationSeconds":live.DURATION,
                       "recordings":{key:sorted({c["root_cause"] for c in CASES if c["fault"]==key and c["root_cause"] in subjects}) for key in LABELS}}
            return self.send(200,"application/json",json.dumps(catalog).encode())
        if self.path == "/state":
            with lock:
                if pending_live_write is not None:
                    checkpoint(pending_live_write)
                payload = json.dumps(state, ensure_ascii=False).encode()
            return self.send(200,"application/json; charset=utf-8",payload)
        if self.path == "/":
            return self.send(200,"text/html; charset=utf-8",(HERE/"screens.html").read_bytes())
        return self.send_error(404)

    def do_POST(self):
        global pending_live_write
        if self.path != "/start": return self.send_error(404)
        if self.headers.get("Origin")!=ORIGIN or self.headers.get("Host")!=live.AUTHORITY:
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
            initial = dict(phase="running", mode=mode, run=run, label=LABELS[fault],
                           location=location, fault=fault, step="요청 접수", started=datetime.now(timezone.utc).isoformat())
            try:
                write_live(state_file, initial)
            except (OSError, ValueError):
                logging.getLogger(__name__).exception("Could not save the requested live run")
                return self.send(503, "text/plain; charset=utf-8", "실험 기록을 저장할 수 없어 주입을 시작하지 않았습니다.".encode())
            if mode == "live":
                pending_live_write = None
            state.clear()
            state.update(initial)
        if mode == "live":
            worker = threading.Thread(target=run_live, args=(manifest,), daemon=True)
        else:
            worker = threading.Thread(target=analyze, args=(next(c for c in CASES if c["fault"]==fault and c["root_cause"]==location),run), daemon=True)
        worker.start()
        self.send(202,"application/json",b'{"accepted":true}')


if __name__=="__main__":
    configured = os.environ.get("SENTRIX_EXHIBIT_STATE_FILE")
    if configured:
        state_file = Path(configured)
        if not state_file.is_absolute():
            raise ValueError("SENTRIX_EXHIBIT_STATE_FILE must be an absolute path")
        state = restore_live(state_file)
    server=ThreadingHTTPServer(("127.0.0.1",live.PORT),Handler)
    pending=playback.ROOT/"active-environment"
    if pending.exists():
        env=pending.read_text()
        if not env.isdecimal() or int(env)<=1 or not (playback.ROOT/env/"source.json").is_file():
            raise ValueError("전시 환경 식별자를 확인하세요.")
        monitor(int(env),False)
        pending.unlink()
    server.serve_forever()
