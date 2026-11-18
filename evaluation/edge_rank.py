"""Statistical edge ranking for edge faults (frozen in R5, docs/METHOD-FREEZE.md section 4).

RE2-OB has no edge-level ground truth, so this rule is fixed without being tuned on any result.

Candidates: directed edges (caller -> callee) with a finite client-side p90 in the case's
baseline_stats windows. Per edge, baseline = median over baseline_stats windows of p90 and err.
Window score: within one window, percentile rank among candidate edges of |log((p90+eps)/(base+eps))|
and of (err - base err); score = max of the two ranks (NaN ignored), as in stat_combined.
Case score: mean over fault_active windows with meta_rel in HORIZON. A candidate with no finite
score, or a true edge that is not a candidate, is ranked last.
"""
import numpy as np
import pandas as pd

from evaluation.aggregate import HORIZON
from features.compute import EPS_LAT


def edge_window_scores(edges):
    """edges: rows (meta_case_id, meta_window, meta_rel, meta_label, meta_src, meta_dst, calls, err, p90)."""
    e = edges.copy()
    e["edge"] = e["meta_src"] + "->" + e["meta_dst"]
    base = (e[e["meta_label"] == "baseline_stats"].groupby(["meta_case_id", "edge"])[["p90", "err"]]
            .median().rename(columns={"p90": "base_p90", "err": "base_err"}))
    base = base[np.isfinite(base["base_p90"])]
    e = e.join(base, on=["meta_case_id", "edge"], how="inner")
    e["lr_abs"] = np.abs(np.log((e["p90"] + EPS_LAT) / (e["base_p90"] + EPS_LAT)))
    e["err_d"] = e["err"] - e["base_err"]
    keys = ["meta_case_id", "meta_window"]
    r_lat = e.groupby(keys)["lr_abs"].rank(pct=True)
    r_err = e.groupby(keys)["err_d"].rank(pct=True)
    e["s_edge"] = pd.concat([r_lat, r_err], axis=1).max(axis=1, skipna=True)
    return e, {c: sorted(g.index.get_level_values("edge")) for c, g in base.groupby(level="meta_case_id")}


def edge_case_rankings(edges, roots, metas=None):
    """roots: case_id -> true edge "src->dst". Yield (case_id, scores, true_index, meta) like case_rankings."""
    e, cands = edge_window_scores(edges)
    lo, hi = HORIZON
    act = e[(e["meta_label"] == "fault_active") & (e["meta_rel"] >= lo) & (e["meta_rel"] < hi)]
    means = act.groupby(["meta_case_id", "edge"])["s_edge"].mean()
    for case_id in sorted(roots):
        c = list(cands.get(case_id, []))
        true = roots[case_id]
        if true not in c:
            c.append(true)                      # not observable in baseline -> scored NaN -> ranked last
        scores = np.array([means.get((case_id, k), np.nan) for k in c], dtype=float)
        meta = {"case_id": case_id, "root_cause": true, "candidates": c} | ((metas or {}).get(case_id, {}))
        yield case_id, scores, c.index(true), meta
