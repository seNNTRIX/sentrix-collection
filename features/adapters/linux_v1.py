"""linux-v1 (self-collected, Online Boutique on k3s) -> common long format.

Same contract as features.adapters.re2ob (features/adapters/__init__.py). The method is frozen
(docs/METHOD-FREEZE-v2.md, commit 399d3d0); this adapter only translates data, following
docs/LINUX-V1-DATA-TRANSLATION.md (2026-11-16, before any linux-v1 feature/score was looked at).

Inputs per dataset root (campaigns/linux-v1/dataset-roots.yaml):
  <root>/runs/<run_id>/runtime.json, fault-record.json (fault runs), pipeline-v2.json
  <root>/runs/<run_id>/<pipeline views.canonical>/{metrics,traces,logs}.parquet, canonicalize-summary.json
  <root>/incidents/inc-<fault_run_id>.yaml      (validity, impact, recovery)
  <root>/audits/pair-<fault_run_id>/            (presence marks an attempt; status.json not used for adoption)
  <root>/runs/_campaign/linux-v1/decisions.yaml  (retry_pairs failure causes; optional)

Translation rules (docs/LINUX-V1-DATA-TRANSLATION.md section in brackets)
  times [2]   run_start = runtime.json workload_started_at; injection = injection_requested_at;
              removal = ended_at; recovery = incident recovery.transaction_observation.stable_at or None.
              onset = fault-record started_at for cpu_saturation, network_delay, packet_loss, traffic_surge;
              pod_failure: first canonical kube_container_ready sample (5 s query grid) in
              [started_at, ended_at] where the target service is not ready (min over its containers = 0);
              none -> started_at with onset_source "fallback_started_at".
              Control run: every time = control run_start + (fault time - fault run_start).
  metrics [1,3]
              cpu_cores       = stored rate[60s] (group container_cpu_usage_rate; no raw counter exported)
              cpu_limit_ratio = cpu_cores / (container_spec_cpu_quota / container_spec_cpu_period)
              mem_limit_ratio = container_memory_working_set_bytes / kube limit (resource=memory)
              net_drop_pkts   = rx + tx dropped rate, pod-level series (POD exception: network only)
              net_rx_pkts, net_tx_pkts: not collected -> no rows -> NaN features
              CPU/memory use application containers only (container label not empty and not "POD").
              Several series of one service at one instant are summed (one pod per service in linux-v1;
              a replaced container shows up as a new series). Components are joined on the exact query
              timestamp, nothing is forward-filled; export-tolerated missing points
              (tolerated_missing_points_unix) force NaN on every grid point they fall into.
  spans       OTel spans; parent join exactly as re2ob.load_spans; err = status code ERROR;
              spans without a canonical service (load generator, unknown) are dropped after the join.
  logs        err = severity/level (JSON body "severity" or "level", else Loki label detected_level)
              in re2ob.ERROR_LEVELS, or a non-empty JSON "error" field. Pino numeric levels >= 40 count.
              message and labels_json are kept for the R8 log extractor (keep_text=True).
"""
from dataclasses import dataclass, field, replace
from datetime import datetime
import csv
import importlib.util
import json
import math
from pathlib import Path
import re

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import yaml

from features.adapters import Case
from features.adapters.re2ob import ERROR_LEVELS, NAME_MAP, resample
from features.schema import CANDIDATES, RESAMPLE_SECONDS

CAMPAIGN = "linux-v1"
DATASET = "linux-v1"
CASE_PREFIX = "lv1_"
EXPECTED_PAIRS = 69
RUN_PREFIX = CAMPAIGN + "-"            # excludes calib-linux-v1-*, calib2-*, ...
ONSET_FROM_STARTED = {"cpu_saturation", "network_delay", "packet_loss", "traffic_surge"}
APP_CONTAINER_EXCLUDED = {None, "", "POD"}
MAX_ATTEMPTS = 9

G_CPU = "container_cpu_usage_rate"
G_MEM = "container_memory_working_set_bytes"
G_QUOTA = "container_spec_cpu_quota"
G_PERIOD = "container_spec_cpu_period"
G_MEM_LIMIT = "kube_container_memory_limit_bytes"
G_RX_DROP = "container_network_receive_dropped_rate"
G_TX_DROP = "container_network_transmit_dropped_rate"
G_READY = "kube_container_ready"
METRIC_GROUPS = (G_CPU, G_MEM, G_QUOTA, G_PERIOD, G_MEM_LIMIT, G_RX_DROP, G_TX_DROP)
SIGNAL_GROUPS = {   # export groups each signal is built from (for tolerated-gap masking)
    "cpu_cores": (G_CPU,),
    "cpu_limit_ratio": (G_CPU, G_QUOTA, G_PERIOD),
    "mem_limit_ratio": (G_MEM, G_MEM_LIMIT),
    "net_drop_pkts": (G_RX_DROP, G_TX_DROP),
}
NOT_COLLECTED_SIGNALS = ("net_rx_pkts", "net_tx_pkts")
POD_HASH = re.compile(r"-[a-z0-9]{6,10}-[a-z0-9]{5}$")   # deployment pod suffix
ERROR_STATUS = {"STATUS_CODE_ERROR", "2", 2}


class _IncidentLoader(yaml.SafeLoader):
    """SafeLoader that reads the !!python/tuple tags of older incident records as lists
    (scripts/generate-incident-record.py writes plain lists since; nothing else is constructed)."""


_IncidentLoader.add_constructor("tag:yaml.org,2002:python/tuple",
                                lambda loader, node: loader.construct_sequence(node))


class DatasetCheckError(RuntimeError):
    """A dataset-level check failed; the build must stop."""


@dataclass(frozen=True)
class LinuxV1Case(Case):
    run_id: str = ""
    root_name: str = ""
    root_dir: Path | None = None
    view: str = ""                       # canonical view folder name inside the run folder
    attempt: int = 1
    schedule_index: int = 0
    environment_id: str = ""
    onset_source: str = ""               # started_at | ready_zero | fallback_started_at | sham_of_fault
    started_at: float | None = None      # fault-record started_at (control: sham)
    edge_src: str | None = None
    edge_dst: str | None = None
    data_valid: bool = True
    injection_valid: bool = True
    impact_confirmed: bool = True
    status: str = ""
    view_hashes: dict = field(default_factory=dict, compare=False, hash=False)


@dataclass(frozen=True)
class Root:
    name: str
    path: Path
    environment_id: str

    @property
    def runs(self):
        return self.path / "runs"

    def decisions(self):
        p = self.runs / "_campaign" / CAMPAIGN / "decisions.yaml"
        return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


# ---------------------------------------------------------------- helpers

def ts(value):
    """ISO-8601 string -> Unix seconds (float); None stays None."""
    if value in (None, ""):
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


def service_name(canonical_id, raw=None):
    """Canonical candidate name or None. canonicalize.py's resolution first; the raw id as a
    fallback (RE2 aliases, pod hash stripped)."""
    if canonical_id in CANDIDATES:
        return canonical_id
    if not isinstance(raw, str) or not raw:
        return None
    raw = NAME_MAP.get(raw, raw)
    if raw in CANDIDATES:
        return raw
    stripped = POD_HASH.sub("", raw)
    stripped = NAME_MAP.get(stripped, stripped)
    return stripped if stripped in CANDIDATES else None


def _services(df):
    return [service_name(c, r) for c, r in zip(df["canonical_service_id"], df["raw_service_id"])]


def load_roots(spec):
    """dataset-roots.yaml path, or a list of Root / dicts."""
    if isinstance(spec, (str, Path)):
        spec = yaml.safe_load(Path(spec).read_text(encoding="utf-8"))["roots"]
    roots = []
    for r in spec:
        roots.append(r if isinstance(r, Root) else
                     Root(name=str(r["name"]), path=Path(r["path"]), environment_id=str(r.get("environment_id", r["name"]))))
    if len({r.name for r in roots}) != len(roots):
        raise DatasetCheckError("duplicate root names in dataset roots")
    return roots


def read_schedule(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["schedule_index"] = int(r["schedule_index"])
        r["repetition"] = int(r["repetition"])
    return rows


def _pair_attempts_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "pair_attempts.py"
    spec = importlib.util.spec_from_file_location("sentrix_pair_attempts", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- dataset checks and pairs

def run_index(roots):
    """{run_id: Root}. Stops if one linux-v1 run ID exists in two roots (check 1)."""
    index, clashes = {}, []
    for root in roots:
        if not root.runs.is_dir():
            raise DatasetCheckError(f"root {root.name}: {root.runs} not found")
        for d in sorted(root.runs.iterdir()):
            if not (d.is_dir() and d.name.startswith(RUN_PREFIX)):
                continue
            if d.name in index:
                clashes.append((d.name, index[d.name].name, root.name))
            else:
                index[d.name] = root
    if clashes:
        raise DatasetCheckError(f"run ID collision between roots (stop): {clashes}")
    return index


def _incident(root, fault_run_id):
    p = root.path / "incidents" / f"inc-{fault_run_id}.yaml"
    return yaml.load(p.read_text(encoding="utf-8"), Loader=_IncidentLoader) if p.exists() else None


def resolve_pairs(roots, schedule_rows, expected_pairs=EXPECTED_PAIRS):
    """Adopted attempt per schedule pair (checks 1-3).

    An attempt is valid when its fault-run incident exists with validity.is_valid_run true, names the
    attempt's control run, and both run folders are in that incident's root. Exactly one valid attempt
    per pair (scripts/pair_attempts.adopted_attempt). Every other attempt is excluded with the failure
    cause from decisions.yaml retry_pairs. Every linux-v1 run folder must belong to some attempt.
    Returns (adopted: list[dict], excluded: list[dict])."""
    pa = _pair_attempts_module()
    index = run_index(roots)
    pair_ids = [r["pair_id"] for r in schedule_rows]
    if len(schedule_rows) != expected_pairs or len(set(pair_ids)) != expected_pairs:
        raise DatasetCheckError(f"schedule has {len(schedule_rows)} rows / {len(set(pair_ids))} pair ids, "
                                f"expected {expected_pairs}")
    if sorted(r["schedule_index"] for r in schedule_rows) != list(range(1, expected_pairs + 1)):
        raise DatasetCheckError("schedule_index is not 1..N without gaps or duplicates")
    causes = {}
    for root in roots:
        for e in (root.decisions() or {}).get("retry_pairs") or []:
            causes[(e["pair_id"], int(e["attempt"]) - 1)] = {
                "failure_cause": " ".join(str(e["failure_cause"]).split()),
                "decided_on": str(e.get("decided_on")), "decision_root": root.name}
    adopted, excluded, used_runs = [], [], set()
    for row in sorted(schedule_rows, key=lambda r: r["schedule_index"]):
        attempts = []
        for n in range(1, MAX_ATTEMPTS + 1):
            f_id, c_id = pa.attempt_id(row["fault_run_id"], n), pa.attempt_id(row["control_run_id"], n)
            has_audit = any((r.path / "audits" / f"pair-{f_id}").is_dir() for r in roots)
            if f_id in index or c_id in index or has_audit:
                attempts.append((n, f_id, c_id))
        info = {}
        for n, f_id, c_id in attempts:
            root = index.get(f_id)
            inc = _incident(root, f_id) if root else None
            valid = bool(inc and (inc.get("validity") or {}).get("is_valid_run") is True
                         and inc.get("control_run_id") == c_id and index.get(c_id) is root)
            info[n] = {"root": root, "incident": inc, "valid": valid}
        chosen = pa.adopted_attempt(attempts, lambda a: info[a[0]]["valid"])   # raises on two valid
        if chosen is None:
            raise DatasetCheckError(f"pair {row['pair_id']}: no valid attempt among {[a[0] for a in attempts]}")
        n, f_id, c_id = chosen
        used_runs.update({f_id, c_id})
        adopted.append({**row, "attempt": n, "fault_id": f_id, "control_id": c_id,
                        "root": info[n]["root"], "incident": info[n]["incident"]})
        for m, mf, mc in attempts:
            if m == n:
                continue
            used_runs.update({mf, mc})
            excluded.append({"pair_id": row["pair_id"], "schedule_index": row["schedule_index"], "attempt": m,
                             "fault_run_id": mf, "control_run_id": mc,
                             "run_folders": {rid: index[rid].name for rid in (mf, mc) if rid in index},
                             **causes.get((row["pair_id"], m), {"failure_cause": None})})
    if {a["pair_id"] for a in adopted} != set(pair_ids) or len(adopted) != expected_pairs:
        raise DatasetCheckError(f"adopted pairs {len(adopted)} != schedule {expected_pairs}")
    stray = sorted(set(index) - used_runs)
    if stray:
        raise DatasetCheckError(f"linux-v1 run folders not belonging to any schedule attempt: {stray}")
    missing_cause = [e["fault_run_id"] for e in excluded if not e["failure_cause"]]
    if missing_cause:
        raise DatasetCheckError(f"excluded attempts without a recorded failure cause: {missing_cause}")
    return adopted, excluded


# ---------------------------------------------------------------- cases

def _view(run_dir):
    pipe = _json(run_dir / "pipeline-v2.json")
    if not pipe.get("complete"):
        raise DatasetCheckError(f"{run_dir.name}: pipeline-v2.json not complete")
    view = pipe["views"]["canonical"]
    hashes = {k.split("/", 1)[1]: v for k, v in (pipe.get("hashes") or {}).items()
              if k.startswith(view + "/") and k.endswith(".parquet")}
    return view, hashes


def _label_map(labels_json, key):
    """Parse each distinct labels_json once; return the `key` label per row (None if absent)."""
    codes, uniques = pd.factorize(labels_json, use_na_sentinel=True)
    vals = np.array([json.loads(u).get(key) if isinstance(u, str) else None for u in uniques] + [None], dtype=object)
    return pd.Series(vals[codes], index=labels_json.index)


def read_metric_groups(path, groups, columns, batch_rows=131_072):
    """Rows of the given metric groups only, read batch by batch (the full labels_json column of a
    canonical metrics.parquet would take ~2.4 GB)."""
    f = pq.ParquetFile(path)
    want = pa.array(list(groups))
    cols = list(dict.fromkeys(list(columns) + ["metric_group"]))
    parts = [b.filter(pc.is_in(b.column("metric_group"), value_set=want))
             for b in f.iter_batches(batch_size=batch_rows, columns=cols)]
    parts = [b for b in parts if b.num_rows]
    if not parts:
        return pd.DataFrame(columns=cols)
    return pa.Table.from_batches(parts).to_pandas()


def _app_containers(df):
    c = df["container"]
    return df[c.notna() & ~c.isin(APP_CONTAINER_EXCLUDED)]


def ready_onset(run_dir, view, service, started_at, ended_at):
    """First 5 s grid time in [started_at, ended_at] where `service` is not ready, else None."""
    df = read_metric_groups(run_dir / view / "metrics.parquet", [G_READY],
                            ["timestamp_unix", "canonical_service_id", "raw_service_id", "value", "labels_json"])
    if df.empty:
        return None
    df = df[pd.Series(_services(df), index=df.index) == service].copy()
    df["container"] = _label_map(df["labels_json"], "container")
    per_t = _app_containers(df).groupby("timestamp_unix")["value"].min()
    hit = per_t[(per_t.index >= started_at) & (per_t.index <= ended_at) & (per_t == 0)]
    return float(hit.index.min()) if len(hit) else None


def _root_cause(row, fr):
    kind = row["target_kind"]
    if kind == "service_node":
        return row["target_id"], None, None
    if kind == "dependency_edge":
        src, dst = fr.get("source_service"), fr.get("destination_service")
        if not (src in CANDIDATES and dst in CANDIDATES):
            raise DatasetCheckError(f"{row['pair_id']}: edge endpoints {src}->{dst} not canonical")
        return f"{src}->{dst}", src, dst
    if kind == "workload_entrypoint":
        return "workload->frontend", None, None
    raise DatasetCheckError(f"{row['pair_id']}: unknown target_kind {kind}")


def pair_cases(pair, resolve_pod_onset=True):
    """(fault Case, control Case) of one adopted pair (dict from resolve_pairs)."""
    root, inc = pair["root"], pair["incident"]
    f_dir, c_dir = root.runs / pair["fault_id"], root.runs / pair["control_id"]
    f_rt, c_rt, fr = _json(f_dir / "runtime.json"), _json(c_dir / "runtime.json"), _json(f_dir / "fault-record.json")
    for rid, rt in ((pair["fault_id"], f_rt), (pair["control_id"], c_rt)):
        if str(rt.get("environment_id")) != root.environment_id:
            raise DatasetCheckError(f"{rid}: environment_id {rt.get('environment_id')} != root {root.name} "
                                    f"({root.environment_id})")
    if fr.get("type") != pair["fault_type"]:
        raise DatasetCheckError(f"{pair['fault_id']}: fault-record type {fr.get('type')} != schedule {pair['fault_type']}")
    f_view, f_hash = _view(f_dir)
    c_view, c_hash = _view(c_dir)
    run_start, started, ended = ts(f_rt.get("workload_started_at")), ts(fr.get("started_at")), ts(fr.get("ended_at"))
    injection = ts(fr.get("injection_requested_at"))
    control_start = ts(c_rt.get("workload_started_at"))
    recovery = ts(((inc.get("recovery") or {}).get("transaction_observation") or {}).get("stable_at"))
    if None in (run_start, started, ended, injection, control_start):
        raise DatasetCheckError(f"{pair['fault_id']}: missing workload_started_at/started_at/ended_at/injection_requested_at")
    root_cause, src, dst = _root_cause(pair, fr)
    if pair["fault_type"] in ONSET_FROM_STARTED:
        onset, source = started, "started_at"
    elif pair["fault_type"] == "pod_failure":
        hit = ready_onset(f_dir, f_view, root_cause, started, ended) if resolve_pod_onset else None
        onset, source = (hit, "ready_zero") if hit is not None else (started, "fallback_started_at")
        if not resolve_pod_onset:
            source = "unresolved"
    else:
        raise DatasetCheckError(f"{pair['fault_id']}: no onset rule for {pair['fault_type']}")
    val = inc.get("validity") or {}
    data_valid = val.get("is_valid_run") is True
    injection_valid = val.get("injector_succeeded") is True and val.get("removal_confirmed") is True
    impact = (inc.get("impact") or {}).get("confirmed") is True
    fault = LinuxV1Case(
        case_id=CASE_PREFIX + pair["fault_id"], root_cause=root_cause, fault=pair["fault_type"],
        repetition=pair["repetition"], onset=onset, path=f_dir, kind="fault", target_kind=pair["target_kind"],
        pair_id=pair["pair_id"], run_start=run_start, injection=injection, removal=ended, recovery=recovery,
        eligible=data_valid and injection_valid and impact, run_id=pair["fault_id"], root_name=root.name,
        root_dir=root.path, view=f_view, attempt=pair["attempt"], schedule_index=pair["schedule_index"],
        environment_id=root.environment_id, onset_source=source, started_at=started, edge_src=src, edge_dst=dst,
        data_valid=data_valid, injection_valid=injection_valid, impact_confirmed=impact,
        status=str(inc.get("status")), view_hashes=f_hash)
    return fault, sham_case(fault, pair["control_id"], c_dir, control_start, c_view, c_hash)


def sham_case(fault, control_id, control_dir, control_start, view, view_hashes):
    """Control run Case: each time = control run_start + (fault time - fault run_start)."""
    def shift(t):
        return None if t is None else control_start + (t - fault.run_start)
    return replace(fault, case_id=CASE_PREFIX + control_id, run_id=control_id, path=control_dir, kind="control",
                   run_start=control_start, onset=shift(fault.onset), injection=shift(fault.injection),
                   removal=shift(fault.removal), recovery=shift(fault.recovery), started_at=shift(fault.started_at),
                   onset_source="sham_of_fault", view=view, view_hashes=view_hashes)


def list_cases(roots, schedule=None, expected_pairs=EXPECTED_PAIRS, resolve_pod_onset=True):
    """One Case per adopted fault run and one per matched control run (138 for linux-v1).

    roots: dataset-roots.yaml path or list; schedule: schedule.csv path (default campaigns/linux-v1)."""
    roots = load_roots(roots)
    schedule = schedule or Path(__file__).resolve().parents[2] / "campaigns" / CAMPAIGN / "schedule.csv"
    adopted, _ = resolve_pairs(roots, read_schedule(schedule), expected_pairs)
    cases = []
    for pair in adopted:
        cases.extend(pair_cases(pair, resolve_pod_onset))
    return cases


# ---------------------------------------------------------------- telemetry

def tolerated_gaps(case):
    """{group: {service or "*": [unix seconds]}} from canonicalize-summary.json, else the export manifest."""
    summ = case.path / case.view / "canonicalize-summary.json"
    if summ.exists():
        gaps = (_json(summ).get("metrics") or {}).get("tolerated_missing_points_unix")
        if gaps:
            return gaps
    manifest = case.path / "raw-v2" / "export-manifest.json"
    if manifest.exists():
        metrics = _json(manifest).get("metrics") or {}
        return {g: r["tolerated_missing_points_unix"] for g, r in metrics.items()
                if isinstance(r, dict) and r.get("tolerated_missing_points_unix")}
    return {}


def grid_for(case, t_min, t_max):
    start = case.onset + math.ceil((t_min - case.onset) / RESAMPLE_SECONDS) * RESAMPLE_SECONDS
    return np.arange(start, t_max + 1e-9, RESAMPLE_SECONDS)


def _summed(df, group, app):
    """(service, t) -> value of one export group summed over its series."""
    g = df[df["metric_group"] == group]
    if app:
        g = _app_containers(g)
    else:   # pod-level network series: no container label (or POD)
        g = g[g["container"].isna() | g["container"].isin(APP_CONTAINER_EXCLUDED)]
    return g.groupby(["service", "t"])["value"].sum(min_count=1)


def _ratio(num, den):
    if not len(num) or not len(den):
        return pd.Series(dtype=float)
    return (num / den.where(den > 0)).dropna()


def load_metrics(case):
    """DataFrame[t, service, signal, value] on the case's 5 s grid (aligned to onset)."""
    empty = pd.DataFrame(columns=["t", "service", "signal", "value"])
    df = read_metric_groups(case.path / case.view / "metrics.parquet", METRIC_GROUPS,
                            ["timestamp_unix", "canonical_service_id", "raw_service_id", "metric_group", "value",
                             "labels_json"])
    if df.empty:
        return empty
    df["service"] = _services(df)
    df = df[df["service"].notna()].copy()
    df["container"] = _label_map(df["labels_json"], "container")
    df["t"] = df["timestamp_unix"].round(3)
    cpu, mem = _summed(df, G_CPU, True), _summed(df, G_MEM, True)
    lim = _app_containers(df[df["metric_group"].isin([G_QUOTA, G_PERIOD])]).copy()
    limit_cores = pd.Series(dtype=float)
    if len(lim):
        lim["pod"] = _label_map(lim["labels_json"], "pod")
        piv = lim.pivot_table(index=["service", "pod", "container", "t"], columns="metric_group", values="value",
                              aggfunc="first")
        if G_QUOTA in piv and G_PERIOD in piv:
            cores = piv[G_QUOTA].where(piv[G_QUOTA] > 0) / piv[G_PERIOD].where(piv[G_PERIOD] > 0)
            limit_cores = cores.groupby(level=["service", "t"]).sum(min_count=1)
    rx, tx = _summed(df, G_RX_DROP, False), _summed(df, G_TX_DROP, False)
    signals = {
        "cpu_cores": cpu,
        "cpu_limit_ratio": _ratio(cpu, limit_cores),
        "mem_limit_ratio": _ratio(mem, _summed(df, G_MEM_LIMIT, True)),
        "net_drop_pkts": (rx + tx).dropna() if len(rx) and len(tx) else pd.Series(dtype=float),
    }
    grid = grid_for(case, df["t"].min(), df["t"].max())
    gaps = tolerated_gaps(case)
    rows = []
    for sig, s in signals.items():
        if not len(s):
            continue
        for svc, g in s.groupby(level="service"):
            t = g.index.get_level_values("t").to_numpy(dtype=float)
            v = g.to_numpy(dtype=float)
            ok = ~np.isnan(v)
            if not ok.any():
                continue
            out = resample(t[ok], v[ok], grid)
            for grp in SIGNAL_GROUPS[sig]:
                pts = gaps.get(grp) or {}
                for p in list(pts.get(svc, [])) + list(pts.get("*", [])):
                    # resample reads (g-5, g]; a missing point p feeds grid points g in [p, p+5)
                    out[(grid >= p - 1e-6) & (grid < p + RESAMPLE_SECONDS - 1e-6)] = np.nan
            rows.append(pd.DataFrame({"t": grid, "service": svc, "signal": sig, "value": out}))
    return pd.concat(rows, ignore_index=True) if rows else empty


def load_spans(case):
    """DataFrame[t, dur_s, service, parent_service, parent_dur_s, err, parent_err] (as re2ob.load_spans)."""
    cols = ["span_id", "parent_span_id", "canonical_service_id", "raw_service_id", "start_time_unix_nano",
            "end_time_unix_nano", "status_code", "timestamp_valid"]
    sp = pq.read_table(case.path / case.view / "traces.parquet", columns=cols).to_pandas()
    sp = sp[sp["timestamp_valid"].fillna(False).astype(bool)].copy()
    sp["service"] = _services(sp)
    start = sp["start_time_unix_nano"].astype("int64")
    sp["t"] = start / 1e9
    sp["dur_s"] = (sp["end_time_unix_nano"].astype("int64") - start) / 1e9
    sp["err"] = sp["status_code"].map(lambda c: c is not None and c in ERROR_STATUS).astype(np.int8)
    parent = sp[["span_id", "service", "dur_s", "err"]].rename(
        columns={"span_id": "parent_span_id", "service": "parent_service", "dur_s": "parent_dur_s",
                 "err": "parent_err"}).drop_duplicates("parent_span_id")
    sp = sp.merge(parent, on="parent_span_id", how="left")
    sp = sp.dropna(subset=["t", "dur_s"])
    sp = sp[sp["service"].notna()]
    return sp[["t", "dur_s", "service", "parent_service", "parent_dur_s", "err", "parent_err"]].reset_index(drop=True)


def log_err(message, detected_level):
    """1 if the log line is an error/warning (RE2-OB rule: level in ERROR_LEVELS or non-empty error field)."""
    level, err_field = None, ""
    if isinstance(message, str) and message.lstrip()[:1] == "{":
        try:
            body = json.loads(message)
        except ValueError:
            body = None
        if isinstance(body, dict):
            level = body.get("severity", body.get("level"))
            e = body.get("error")
            err_field = "" if e is None else str(e).strip()
    if level is None:
        level = detected_level
    if isinstance(level, (int, float)) and not isinstance(level, bool):
        is_err = level >= 40                                      # pino: 40 warn, 50 error, 60 fatal
    else:
        is_err = str(level or "").strip().lower() in ERROR_LEVELS
    return int(is_err or err_field != "")


def load_logs(case, keep_text=True):
    """DataFrame[t, service, err] (+ message, labels_json when keep_text) from canonical Loki logs."""
    cols = ["timestamp_unix_nano", "canonical_service_id", "raw_service_id", "message", "labels_json"]
    lg = pq.read_table(case.path / case.view / "logs.parquet", columns=cols).to_pandas()
    lg["service"] = _services(lg)
    lg = lg[lg["service"].notna()].copy()
    lg["t"] = lg["timestamp_unix_nano"].astype("int64") / 1e9
    detected = _label_map(lg["labels_json"], "detected_level")
    lg["err"] = np.fromiter((log_err(m, d) for m, d in zip(lg["message"], detected)), dtype=np.int8, count=len(lg))
    keep = ["t", "service", "err"] + (["message", "labels_json"] if keep_text else [])
    return lg[keep].sort_values("t", kind="stable").reset_index(drop=True)
