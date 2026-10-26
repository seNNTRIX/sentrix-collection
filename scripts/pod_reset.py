"""Pre-pair reset of memory-leaking services (campaigns/<id>/pre-pair-reset.yaml).

currencyservice and paymentservice leak ~22 MiB/h and are OOM-killed at their
512Mi limit about every 22.5 h, with or without load (206-39 investigation,
SETUP-REVIEW 7.19). A restart inside a run invalidates the control or mixes an
unrelated anomaly into the fault data, so every pair starts from fresh pods.

The pods are deleted with `kubectl delete pod` and their ReplicaSet recreates
them from the unchanged template. `kubectl rollout restart` is NOT used: it
writes a restartedAt annotation into the Deployment pod template, which is part
of the environment fingerprint (run-attended.snapshot) and would break control
matching.
"""
from datetime import datetime, timezone
from pathlib import Path
import time

import yaml


def now():
    return datetime.now(timezone.utc).isoformat()


def load_config(path):
    """-> config dict, or None when the campaign has no reset file."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    cfg = yaml.safe_load(text) or {}
    services = cfg.get("services")
    if not services or not all(isinstance(s, str) and s for s in services):
        raise ValueError(f"{path}: services must be a non-empty list of app labels")
    return {"namespace": cfg.get("namespace", "sentrix"), "services": list(services),
            "ready_timeout_seconds": int(cfg.get("ready_timeout_seconds", 300)),
            "poll_seconds": float(cfg.get("poll_seconds", 2))}


def pod_ready(pod):
    statuses = pod.get("status", {}).get("containerStatuses") or []
    return (pod.get("status", {}).get("phase") == "Running" and not pod["metadata"].get("deletionTimestamp")
            and bool(statuses) and all(c.get("ready") for c in statuses))


def describe(pod):
    return {"name": pod["metadata"]["name"], "uid": pod["metadata"]["uid"],
            "restarts": {c["name"]: c.get("restartCount") for c in pod.get("status", {}).get("containerStatuses") or []}}


def reset(cfg, kubectl_json, kubectl, clock=time.monotonic, sleep=time.sleep, note=print):
    """Delete every pod of cfg['services'] and wait until each service has only
    new, Ready pods. Returns the record of what was deleted and when; raises
    TimeoutError (nothing else may start) when a service is not Ready in time."""
    ns = cfg["namespace"]
    record = {"namespace": ns, "services": {}, "started_at": now()}
    old = {}
    for svc in cfg["services"]:
        pods = kubectl_json("get", "pods", "-n", ns, "-l", "app=" + svc)["items"]
        if not pods:
            raise RuntimeError(f"pre-pair reset: no pod for app={svc}")
        old[svc] = {p["metadata"]["uid"] for p in pods}
        names = [p["metadata"]["name"] for p in pods]
        kubectl("delete", "pod", "-n", ns, "--wait=false", *names)
        deleted_at = now()
        record["services"][svc] = {"deleted": [describe(p) for p in pods], "deleted_at": deleted_at}
        note(f"pre-pair reset: deleted {svc} pod(s) {', '.join(names)} at {deleted_at}")
    deadline = clock() + cfg["ready_timeout_seconds"]
    pending = list(cfg["services"])
    while pending:
        for svc in list(pending):
            pods = kubectl_json("get", "pods", "-n", ns, "-l", "app=" + svc)["items"]
            fresh = [p for p in pods if p["metadata"]["uid"] not in old[svc]]
            if pods and len(fresh) == len(pods) and all(pod_ready(p) for p in fresh):
                ready_at = now()
                record["services"][svc].update(new=[describe(p) for p in fresh], ready_at=ready_at)
                note(f"pre-pair reset: {svc} ready with new pod(s) "
                     f"{', '.join(p['metadata']['name'] for p in fresh)} at {ready_at}")
                pending.remove(svc)
        if not pending:
            break
        if clock() > deadline:
            record["timed_out"] = pending
            raise TimeoutError(f"pre-pair reset: {', '.join(pending)} not Ready within "
                               f"{cfg['ready_timeout_seconds']}s")
        sleep(cfg["poll_seconds"])
    record["finished_at"] = now()
    return record
