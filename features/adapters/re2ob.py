"""RCAEval RE2-OB (Zenodo release) -> common long format.

Facts used here are recorded in docs/RE2OB-INVENTORY.md and docs/RE2OB-DECISIONS.md:
- case folder RE2-OB/<service>_<fault>/<repetition>/, inject_time.txt in Unix seconds
- metrics.csv: 1 Hz, "*-total" columns are already rates; CPU in cores x 100
- traces.csv: startTime in microseconds, duration in microseconds, serviceName
  "frontendservice" for the frontend
- logs.csv: timestamp in nanoseconds, container_name, level, error
"""
import math
from pathlib import Path

import numpy as np
import pandas as pd

from features.adapters import Case
from features.schema import CANDIDATES, RESAMPLE_SECONDS

NAME_MAP = {"frontendservice": "frontend", "redis": "redis-cart"}
EXCLUDED_DIRS = {"multi-source-data"}
CFS_PERIOD_US = 100_000  # Kubernetes default; RE2-OB has no period column
ERROR_LEVELS = {"error", "err", "warn", "warning", "fatal", "critical", "severe"}


def canonical(name):
    name = NAME_MAP.get(name, name)
    return name if name in CANDIDATES else None


def list_cases(root):
    root = Path(root)
    cases = []
    for inject in sorted(root.glob("*_*/*/inject_time.txt")):
        rep_dir = inject.parent
        if rep_dir.name in EXCLUDED_DIRS or not rep_dir.name.isdigit():
            continue
        service, fault = rep_dir.parent.name.rsplit("_", 1)
        cases.append(Case(case_id=f"re2ob_{service}_{fault}_{rep_dir.name}", root_cause=service,
                          fault=fault, repetition=int(rep_dir.name),
                          onset=float(inject.read_text().strip()), path=rep_dir))
    return cases


def resample(times, values, grid):
    """Last observed value in (g - RESAMPLE_SECONDS, g] for each grid point g, else NaN."""
    order = np.argsort(times)
    times, values = times[order], values[order]
    idx = np.searchsorted(times, grid, side="right") - 1
    out = np.full(len(grid), np.nan)
    ok = idx >= 0
    fresh = ok.copy()
    fresh[ok] = times[idx[ok]] > grid[ok] - RESAMPLE_SECONDS
    out[fresh] = values[idx[fresh]]
    return out


def grid_for(case, t_min, t_max):
    start = case.onset + math.ceil((t_min - case.onset) / RESAMPLE_SECONDS) * RESAMPLE_SECONDS
    return np.arange(start, t_max + 1e-9, RESAMPLE_SECONDS)


def load_metrics(case):
    raw = pd.read_csv(case.path / "metrics.csv")
    raw = raw[pd.to_numeric(raw["time"], errors="coerce").notna()]
    t = raw["time"].astype(float).to_numpy()
    grid = grid_for(case, t.min(), t.max())

    def col(service, name):
        c = f"{service}_{name}"
        return pd.to_numeric(raw[c], errors="coerce").to_numpy(dtype=float) if c in raw else None

    rows = []
    for col_name in raw.columns:
        prefix = col_name.split("_", 1)[0]
        svc = canonical(prefix)
        if svc is None or not col_name.endswith("_container-cpu-usage-seconds-total"):
            continue
        cpu = col(prefix, "container-cpu-usage-seconds-total") / 100.0
        quota = col(prefix, "container-spec-cpu-quota")
        limit_cores = quota / CFS_PERIOD_US if quota is not None else None
        mem = col(prefix, "container-memory-working-set-bytes")
        mem_limit = col(prefix, "container-spec-memory-limit-bytes")
        drop = [col(prefix, f"container-network-{d}-packets-dropped-total") for d in ("receive", "transmit")]
        signals = {
            "cpu_cores": cpu,
            "cpu_limit_ratio": cpu / np.where(limit_cores > 0, limit_cores, np.nan) if limit_cores is not None else None,
            "mem_limit_ratio": mem / np.where(mem_limit > 0, mem_limit, np.nan)
            if mem is not None and mem_limit is not None else None,
            "net_rx_pkts": col(prefix, "container-network-receive-packets-total"),
            "net_tx_pkts": col(prefix, "container-network-transmit-packets-total"),
            "net_drop_pkts": drop[0] + drop[1] if drop[0] is not None and drop[1] is not None else None,
        }
        for sig, values in signals.items():
            if values is None:
                continue
            ok = ~np.isnan(values)
            if not ok.any():
                continue
            rows.append(pd.DataFrame({"t": grid, "service": svc, "signal": sig,
                                      "value": resample(t[ok], values[ok], grid)}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["t", "service", "signal", "value"])


def load_spans(case):
    cols = ["spanID", "parentSpanID", "serviceName", "startTime", "duration", "statusCode"]
    sp = pd.read_csv(case.path / "traces.csv", usecols=cols,
                     dtype={"spanID": str, "parentSpanID": str, "serviceName": str})
    sp["service"] = sp["serviceName"].map(canonical)
    sp["t"] = pd.to_numeric(sp["startTime"], errors="coerce") / 1e6
    sp["dur_s"] = pd.to_numeric(sp["duration"], errors="coerce") / 1e6
    code = pd.to_numeric(sp["statusCode"], errors="coerce")
    sp["err"] = (code.notna() & (code != 0)).astype(np.int8)
    parent = sp[["spanID", "service", "dur_s", "err"]].rename(
        columns={"spanID": "parentSpanID", "service": "parent_service", "dur_s": "parent_dur_s",
                 "err": "parent_err"}).drop_duplicates("parentSpanID")
    sp = sp.merge(parent, on="parentSpanID", how="left")
    sp = sp.dropna(subset=["t", "dur_s"])
    sp = sp[sp["service"].notna()]
    return sp[["t", "dur_s", "service", "parent_service", "parent_dur_s", "err", "parent_err"]].reset_index(drop=True)


def load_logs(case):
    lg = pd.read_csv(case.path / "logs.csv", usecols=lambda c: c in {"timestamp", "container_name", "level", "error"},
                     dtype=str)
    lg["service"] = lg["container_name"].map(canonical)
    lg["t"] = pd.to_numeric(lg["timestamp"], errors="coerce") / 1e9
    level = lg["level"].fillna("").str.strip().str.lower()
    err_field = lg["error"].fillna("").str.strip() if "error" in lg else ""
    lg["err"] = (level.isin(ERROR_LEVELS) | (err_field != "")).astype(np.int8)
    lg = lg.dropna(subset=["t"])
    lg = lg[lg["service"].notna()]
    return lg[["t", "service", "err"]].reset_index(drop=True)
