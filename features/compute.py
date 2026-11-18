"""Per-window raw statistics and baseline-normalized features (source independent).

Input frames follow features/adapters/__init__.py. Output columns:
  f_cm_*   core metric features      f_ct_*  core trace features
  f_opt_*  optional (raw levels, slope, p99)  f_log_* experimental logs
  f_nbr_*  experimental neighbour-relative features
Raw absolute levels (f_opt_*) can fingerprint a service; the core bundles use
changes against the same case's own baseline so the model cannot learn names.
"""
import numpy as np
import pandas as pd

from features.schema import CANDIDATES, METRIC_SIGNALS, MIN_SPANS, WINDOW_SECONDS

EPS_LAT = 1e-4   # seconds
EPS_RATE = 1e-3  # per second


def _quantile(x, q, need):
    return float(np.quantile(x, q)) if len(x) >= need else np.nan


def metric_stats(metrics, windows):
    """(window, service) rows with <signal>_{mean,max,std,slope,n}."""
    out = {}
    starts, ends = windows["w_start"].to_numpy(), windows["w_end"].to_numpy()
    for (svc, sig), g in metrics.groupby(["service", "signal"], sort=True):
        g = g.sort_values("t")
        t, v = g["t"].to_numpy(), g["value"].to_numpy(dtype=float)
        lo, hi = np.searchsorted(t, starts, "left"), np.searchsorted(t, ends, "left")
        for wi, (a, b) in enumerate(zip(lo, hi)):
            seg_t, seg = t[a:b], v[a:b]
            ok = ~np.isnan(seg)
            rec = out.setdefault((wi, svc), {})
            rec[f"{sig}_n"] = int(ok.sum())
            if ok.sum() == 0:
                continue
            rec[f"{sig}_mean"] = float(seg[ok].mean())
            rec[f"{sig}_max"] = float(seg[ok].max())
            rec[f"{sig}_std"] = float(seg[ok].std())
            rec[f"{sig}_slope"] = float(np.polyfit(seg_t[ok] - seg_t[ok][0], seg[ok], 1)[0]) if ok.sum() >= 3 else np.nan
    return out


def span_stats(spans, windows):
    """Node incoming-call stats and directed edge (caller->callee) client-side stats."""
    starts, ends = windows["w_start"].to_numpy(), windows["w_end"].to_numpy()
    node, edge = {}, {}
    incoming = spans[spans["parent_service"].isna() | (spans["parent_service"] != spans["service"])]
    for svc, g in incoming.groupby("service", sort=True):
        g = g.sort_values("t")
        t, d, e = g["t"].to_numpy(), g["dur_s"].to_numpy(), g["err"].to_numpy()
        lo, hi = np.searchsorted(t, starts, "left"), np.searchsorted(t, ends, "left")
        for wi, (a, b) in enumerate(zip(lo, hi)):
            n = b - a
            node[(wi, svc)] = {
                "in_rate": n / WINDOW_SECONDS,
                "in_err": float(e[a:b].mean()) if n else np.nan,
                "in_p50": _quantile(d[a:b], 0.5, MIN_SPANS["p50"]),
                "in_p90": _quantile(d[a:b], 0.9, MIN_SPANS["p90"]),
                "in_p99": _quantile(d[a:b], 0.99, MIN_SPANS["p99"]),
            }
    calls = spans[spans["parent_service"].notna() & (spans["parent_service"] != spans["service"])]
    for (src, dst), g in calls.groupby(["parent_service", "service"], sort=True):
        g = g.sort_values("t")
        t = g["t"].to_numpy()
        d = g["parent_dur_s"].fillna(g["dur_s"]).to_numpy()
        e = (g["err"].to_numpy() | g["parent_err"].fillna(0).astype(np.int8).to_numpy())
        lo, hi = np.searchsorted(t, starts, "left"), np.searchsorted(t, ends, "left")
        for wi, (a, b) in enumerate(zip(lo, hi)):
            n = b - a
            edge[(wi, src, dst)] = {
                "calls": n / WINDOW_SECONDS,
                "err": float(e[a:b].mean()) if n else np.nan,
                "p50": _quantile(d[a:b], 0.5, MIN_SPANS["p50"]),
                "p90": _quantile(d[a:b], 0.9, MIN_SPANS["p90"]),
            }
    return node, edge


def log_stats(logs, windows):
    starts, ends = windows["w_start"].to_numpy(), windows["w_end"].to_numpy()
    out = {}
    for svc, g in logs.groupby("service", sort=True):
        g = g.sort_values("t")
        t, e = g["t"].to_numpy(), g["err"].to_numpy()
        lo, hi = np.searchsorted(t, starts, "left"), np.searchsorted(t, ends, "left")
        csum = np.concatenate([[0], np.cumsum(e)])
        for wi, (a, b) in enumerate(zip(lo, hi)):
            out[(wi, svc)] = {"log_rate": (b - a) / WINDOW_SECONDS,
                              "log_err_rate": (csum[b] - csum[a]) / WINDOW_SECONDS}
    return out


def _baseline(values, base_mask):
    """Median and IQR over baseline windows (NaN-aware)."""
    b = values[base_mask]
    b = b[~np.isnan(b)]
    if len(b) == 0:
        return np.nan, np.nan
    q1, med, q3 = np.quantile(b, [0.25, 0.5, 0.75])
    return med, q3 - q1


def _robust_delta(x, med, iqr):
    if np.isnan(med):
        return np.full_like(x, np.nan), np.zeros_like(x)
    if iqr > 0:
        return (x - med) / iqr, np.zeros_like(x)
    return x - med, np.ones_like(x)   # feature-schema: absolute delta + indicator


def _log_ratio(x, med, eps):
    if np.isnan(med):
        return np.full_like(x, np.nan)
    return np.log((x + eps) / (med + eps))


def node_features(windows, mstats, nstats, estats, lstats, base_mask):
    """One row per (window, candidate) with f_* features; windows index = position."""
    nw = len(windows)
    frames = []
    # Directed edges seen in baseline windows define each node's neighbours.
    base_idx = set(np.flatnonzero(base_mask))
    neighbours = {s: set() for s in CANDIDATES}
    for (wi, src, dst), rec in estats.items():
        if wi in base_idx and rec["calls"] > 0:
            neighbours[src].add(dst)
            neighbours[dst].add(src)
    edge_keys = sorted({(s, d) for _, s, d in estats})
    edge_arr = {k: {f: np.array([estats.get((wi, *k), {}).get(f, np.nan) for wi in range(nw)])
                    for f in ("calls", "err", "p90")} for k in edge_keys}
    edge_base = {k: _baseline(edge_arr[k]["p90"], base_mask)[0] for k in edge_keys}

    for svc in CANDIDATES:
        col = {}

        def series(store, name):
            return np.array([store.get((wi, svc), {}).get(name, np.nan) for wi in range(nw)], dtype=float)

        for sig in METRIC_SIGNALS:
            mean, mx = series(mstats, f"{sig}_mean"), series(mstats, f"{sig}_max")
            med, iqr = _baseline(mean, base_mask)
            col[f"f_cm_{sig}_dmean"], zero = _robust_delta(mean, med, iqr)
            col[f"f_cm_{sig}_dmax"], _ = _robust_delta(mx, med, iqr)
            col[f"f_cm_{sig}_zero_iqr"] = zero if not np.isnan(med) else np.full(nw, np.nan)
            col[f"f_opt_{sig}_mean"] = mean
            col[f"f_opt_{sig}_max"] = mx
            col[f"f_opt_{sig}_std"] = series(mstats, f"{sig}_std")
            col[f"f_opt_{sig}_slope"] = series(mstats, f"{sig}_slope")
            col[f"f_cm_{sig}_n"] = series(mstats, f"{sig}_n")
        for sig in ("cpu_limit_ratio", "mem_limit_ratio"):
            col[f"f_cm_{sig}_mean"] = col[f"f_opt_{sig}_mean"]   # ratios are comparable across services

        rate, err = series(nstats, "in_rate"), series(nstats, "in_err")
        p50, p90, p99 = series(nstats, "in_p50"), series(nstats, "in_p90"), series(nstats, "in_p99")
        traced = not np.isnan(_baseline(rate, base_mask)[0])
        col["f_ct_mask"] = np.full(nw, 1.0 if traced else 0.0)
        col["f_ct_in_rate_lr"] = _log_ratio(rate, _baseline(rate, base_mask)[0], EPS_RATE)
        col["f_ct_in_err"] = err
        emed = _baseline(err, base_mask)[0]
        col["f_ct_in_err_d"] = err - emed if not np.isnan(emed) else np.full(nw, np.nan)
        col["f_ct_in_p50_lr"] = _log_ratio(p50, _baseline(p50, base_mask)[0], EPS_LAT)
        col["f_ct_in_p90_lr"] = _log_ratio(p90, _baseline(p90, base_mask)[0], EPS_LAT)
        col["f_opt_in_p99_lr"] = _log_ratio(p99, _baseline(p99, base_mask)[0], EPS_LAT)
        out_lr, out_err, in_lr = [], [], []
        for (src, dst) in edge_keys:
            lr = _log_ratio(edge_arr[(src, dst)]["p90"], edge_base[(src, dst)], EPS_LAT)
            if src == svc:
                out_lr.append(lr)
                out_err.append(edge_arr[(src, dst)]["err"])
            if dst == svc:
                in_lr.append(lr)
        with np.errstate(all="ignore"):
            col["f_ct_out_p90_lr"] = np.nanmax(np.vstack(out_lr), axis=0) if out_lr else np.full(nw, np.nan)
            col["f_ct_out_err"] = np.nanmax(np.vstack(out_err), axis=0) if out_err else np.full(nw, np.nan)
            col["f_ct_in_edge_p90_lr"] = np.nanmax(np.vstack(in_lr), axis=0) if in_lr else np.full(nw, np.nan)

        lrate, lerr = series(lstats, "log_rate"), series(lstats, "log_err_rate")
        col["f_log_rate_lr"] = _log_ratio(lrate, _baseline(lrate, base_mask)[0], EPS_RATE)
        col["f_log_err_rate"] = lerr
        lmed = _baseline(lerr, base_mask)[0]
        col["f_log_err_rate_d"] = lerr - lmed if not np.isnan(lmed) else np.full(nw, np.nan)

        df = pd.DataFrame(col)
        df.insert(0, "meta_window", np.arange(nw))
        df.insert(1, "meta_candidate", svc)
        frames.append(df)
    feats = pd.concat(frames, ignore_index=True)

    # Experimental: node value minus the median of its neighbours in the same window.
    for name in ("f_cm_cpu_cores_dmean", "f_cm_mem_limit_ratio_dmean", "f_ct_in_p90_lr", "f_ct_in_err_d"):
        piv = feats.pivot(index="meta_window", columns="meta_candidate", values=name)
        rel = {}
        for svc in CANDIDATES:
            nb = sorted(neighbours[svc])
            if nb:
                with np.errstate(all="ignore"):
                    rel[svc] = piv[svc] - piv[nb].median(axis=1, skipna=True)
            else:
                rel[svc] = pd.Series(np.nan, index=piv.index)
        rel = pd.DataFrame(rel).stack(future_stack=True).rename(f"f_nbr_{name[2:]}").reset_index()
        rel.columns = ["meta_window", "meta_candidate", f"f_nbr_{name[2:]}"]
        feats = feats.merge(rel, on=["meta_window", "meta_candidate"], how="left")
    return feats, edge_keys, edge_arr
