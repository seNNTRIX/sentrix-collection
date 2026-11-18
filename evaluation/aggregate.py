"""Window scores -> one candidate ranking per case (rule fixed in R3).

Rule: for each candidate, the case score is the MEAN of its window scores over
fault_active windows whose start lies in [60 s, 300 s) after injection
(docs/RE2OB-DECISIONS.md section 3: same horizon for RE2-OB and linux-v1).
NaN window scores are ignored in the mean; a candidate with no finite score
gets NaN (ranked last). Do not change this rule after looking at results.
"""
import numpy as np
import pandas as pd

from features.schema import CANDIDATES

HORIZON = (60, 300)


def case_rankings(ranking_df, score_col, candidates=CANDIDATES):
    """Yield (case_id, scores aligned to `candidates`, true_index, meta dict)."""
    lo, hi = HORIZON
    df = ranking_df[(ranking_df["meta_rel"] >= lo) & (ranking_df["meta_rel"] < hi)]
    df = df[df["meta_candidate"].isin(candidates)]
    for case_id, g in df.groupby("meta_case_id", sort=True):
        with np.errstate(all="ignore"):
            mean = g.groupby("meta_candidate")[score_col].mean()
        scores = np.array([mean.get(c, np.nan) for c in candidates], dtype=float)
        root = g["meta_root_cause"].iloc[0]
        if root not in candidates:
            continue
        meta = {"case_id": case_id, "fault": g["meta_fault"].iloc[0], "root_cause": root,
                "fold": int(g["meta_fold"].iloc[0]), "n_windows": int(g["meta_window"].nunique())}
        yield case_id, scores, list(candidates).index(root), meta
