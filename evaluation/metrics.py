"""Ranking and detection metrics.

Ranking metrics follow RCAEval (arXiv 2412.17015 v5, section 4.2):
  AC@k  = (1/|A|) sum_a  sum_{i<k} 1(R^a[i] in V^a_rc) / min(k, |V^a_rc|)
  Avg@k = (1/k) sum_{j=1..k} AC@j
Every case here has exactly one root cause, so a case contributes 1 to AC@k
when the root cause is in the top k.

Ties (fixed in R3, docs/RE2OB-DECISIONS.md is not affected):
  scores are compared with NaN treated as -inf. When the root cause shares its
  score with t-1 other candidates and g candidates score strictly higher, its
  rank is taken as uniformly distributed over g+1 .. g+t. AC@k and MRR use the
  expectation over that distribution. This is what an arbitrary tie-break gives
  on average, so a constant-score method gets exactly k/n, not 0 or 1.
"""
import numpy as np


def rank_distribution(scores, true_index):
    """(g, t): number strictly above the root cause, size of its tie group."""
    s = np.where(np.isnan(scores), -np.inf, np.asarray(scores, dtype=float))
    v = s[true_index]
    return int((s > v).sum()), int((s == v).sum())


def case_hit_at(scores, true_index, k):
    g, t = rank_distribution(scores, true_index)
    return float(np.clip((k - g) / t, 0.0, 1.0))


def case_reciprocal_rank(scores, true_index):
    g, t = rank_distribution(scores, true_index)
    return float(np.mean([1.0 / r for r in range(g + 1, g + t + 1)]))


def ranking_summary(cases, ks=(1, 3, 5)):
    """cases: iterable of (scores array, true_index). Returns AC@k, Avg@5, MRR."""
    cases = list(cases)
    if not cases:
        return {}
    out = {}
    hits = {k: np.mean([case_hit_at(s, i, k) for s, i in cases]) for k in range(1, max(ks) + 1)}
    for k in ks:
        out[f"AC@{k}"] = float(hits[k])
    out["Avg@5"] = float(np.mean([hits[j] for j in range(1, 6)]))
    out["MRR"] = float(np.mean([case_reciprocal_rank(s, i) for s, i in cases]))
    out["n_cases"] = len(cases)
    return out


def per_case_scores(cases):
    """Per-case vector of the metrics (for bootstrap)."""
    rows = []
    for s, i in cases:
        hits = [case_hit_at(s, i, k) for k in range(1, 6)]
        rows.append({"AC@1": hits[0], "AC@3": hits[2], "AC@5": hits[4], "Avg@5": float(np.mean(hits)),
                     "MRR": case_reciprocal_rank(s, i)})
    return rows


def bootstrap_ci(per_case, metric, n_boot=2000, seed=0, alpha=0.05):
    """Case-level percentile bootstrap CI of the mean of `metric`."""
    v = np.array([r[metric] for r in per_case], dtype=float)
    if len(v) == 0:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(v), size=(n_boot, len(v)))
    means = v[idx].mean(axis=1)
    return (float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2)))


def detection_summary(y_true, score):
    """AUROC and AUPRC (average precision); NaN scores count as the lowest score."""
    from sklearn.metrics import average_precision_score, roc_auc_score
    y = np.asarray(y_true, dtype=int)
    s = np.where(np.isnan(score), -np.inf, np.asarray(score, dtype=float))
    finite_min = np.min(s[np.isfinite(s)]) if np.isfinite(s).any() else 0.0
    s = np.where(np.isfinite(s), s, finite_min - 1.0)
    return {"AUROC": float(roc_auc_score(y, s)), "AUPRC": float(average_precision_score(y, s)),
            "positive_rate": float(y.mean()), "n_windows": int(len(y))}
