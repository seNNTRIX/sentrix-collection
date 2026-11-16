"""Log clusters for evidence and visualisation only (PREREG R8 section 9). Not a model input.

Groups unique masked log texts by embedding similarity and summarises, per service, how often each cluster
appeared in the baseline reference period versus an analysis interval, with one representative text.
"""
import numpy as np
import pandas as pd


def cluster_texts(vectors, counts, min_cluster_size=3, seed=0):
    """Cluster unique-text vectors (dense, L2-normalised). Returns a label per row (-1 = noise).

    HDBSCAN on cosine distance; each unique text is weighted by repeating it up to min_cluster_size times
    so that a frequent single message can still form its own cluster.
    """
    from sklearn.cluster import HDBSCAN
    vectors = np.asarray(vectors)
    if len(vectors) == 0:
        return np.zeros(0, dtype=int)
    if len(vectors) < min_cluster_size:
        return np.arange(len(vectors))
    reps = np.minimum(np.asarray(counts, dtype=int), min_cluster_size)
    idx = np.repeat(np.arange(len(vectors)), reps)
    labels = HDBSCAN(min_cluster_size=min_cluster_size, metric="cosine").fit_predict(vectors[idx])
    out = np.full(len(vectors), -1)
    for i in range(len(vectors)):
        lab = labels[idx == i]
        lab = lab[lab >= 0]
        out[i] = np.bincount(lab).argmax() if len(lab) else -1
    return out


def cluster_change(logs, text_cluster, ref, interval):
    """Per (service, cluster): count in the reference period, count in the interval, rates per second,
    and the most frequent text of that cluster as its representative.

    logs: columns t, service, text.  text_cluster: dict text -> cluster label.
    ref, interval: (start, end) in Unix seconds, half-open.
    """
    lg = logs.assign(cluster=logs["text"].map(text_cluster).fillna(-1).astype(int))
    rows = []
    for (svc, cl), g in lg.groupby(["service", "cluster"]):
        r = g[(g["t"] >= ref[0]) & (g["t"] < ref[1])]
        a = g[(g["t"] >= interval[0]) & (g["t"] < interval[1])]
        rows.append({
            "service": svc, "cluster": cl,
            "ref_count": len(r), "interval_count": len(a),
            "ref_rate": len(r) / max(ref[1] - ref[0], 1e-9),
            "interval_rate": len(a) / max(interval[1] - interval[0], 1e-9),
            "new_in_interval": len(r) == 0 and len(a) > 0,
            "representative": g["text"].value_counts().index[0],
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["rate_change"] = df["interval_rate"] - df["ref_rate"]
    return df.sort_values(["service", "rate_change"], ascending=[True, False]).reset_index(drop=True)
