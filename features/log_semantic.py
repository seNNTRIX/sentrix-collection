"""Log semantic-change features for R8 (experiments/20261116-log-semantic-r8/PREREG.md, sections 3-5).

Pipeline per case: raw log rows -> body text (+ error field) -> masked text -> vectors (computed once per
unique text) -> distance to the nearest reference log of the same service (D), of all services (C) or with
character n-gram hashing (B) -> per window mean and p90 -> robust delta against the second half of the
baseline_stats period.

Inputs are plain DataFrames so the module does not depend on a dataset adapter:
  logs:    columns t (Unix seconds), service (canonical name), message (raw line), optional error
  windows: columns w_start, w_end, label (from features.windows.make_windows + a label function)
Encoders are callables list[str] -> 2-D array (dense or scipy sparse) of L2-normalised rows.
"""
import json
import re

import numpy as np
import pandas as pd

from features.schema import CANDIDATES

ERROR_KEYS = ("error", "err", "exception")
BODY_KEYS = ("message", "msg", "log")
MIN_DIST_WINDOWS = 5  # second-half baseline windows needed for median/IQR (PREREG 4.4)

# ---------------------------------------------------------------- text


def extract_text(message, error=None):
    """Body text of one log line, with the error field appended as 'body | error' (PREREG 3)."""
    body, err = message if isinstance(message, str) else "", error
    s = body.strip()
    if s.startswith("{"):
        try:
            obj = json.loads(s)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            body = next((str(obj[k]) for k in BODY_KEYS if obj.get(k) not in (None, "")), s)
            if err in (None, ""):
                err = next((obj[k] for k in ERROR_KEYS if obj.get(k) not in (None, "")), None)
    if isinstance(err, (dict, list)):
        err = json.dumps(err, sort_keys=True)
    if err is not None and not (isinstance(err, float) and np.isnan(err)) and str(err).strip():
        return f"{body.strip()} | {str(err).strip()}"
    return body.strip()


_SERVICE_RE = re.compile(r"\b(" + "|".join(sorted((re.escape(c) for c in CANDIDATES), key=len, reverse=True))
                         + r"|redis)\b", re.I)
_MASKS = [  # order matters: specific patterns before the generic number rule
    (re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "<EMAIL>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<ID>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?\b"), "<TIME>"),
    (re.compile(r"\b\d{1,3}(\.\d{1,3}){3}(:\d+)?\b"), "<IP>"),
    (re.compile(r"\b[\w-]+-[0-9a-f]{8,10}-[0-9a-z]{5}\b"), "<POD>"),
    (re.compile(r"\b[0-9a-f]{16,}\b", re.I), "<ID>"),
    (re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z0-9]{8,}\b"), "<ID>"),  # needs a digit: keeps UNAVAILABLE
    (re.compile(r"\$?\d+\.\d+\b"), "<NUM>"),
    (re.compile(r"\b\d{3,}\b"), "<NUM>"),
]
_HTTP_STATUS = re.compile(r"\b(status|code)[ =:]+([1-5]\d\d)\b", re.I)


def mask(text):
    """Replace identifiers, addresses, times, numbers and service names (PREREG 3). HTTP status codes stay."""
    keep = {}

    def _keep(m):
        key = f"__KEEP{len(keep)}__"
        keep[key] = m.group(0)
        return key

    t = _HTTP_STATUS.sub(_keep, text)
    for rx, rep in _MASKS:
        t = rx.sub(rep, t)
    t = _SERVICE_RE.sub("<SERVICE>", t)
    for k, v in keep.items():
        t = t.replace(k, v)
    return re.sub(r"\s+", " ", t).strip()


def prepare_logs(logs, exclude_services=()):
    """Keep candidate services, build masked text. Returns columns t, service, text."""
    lg = logs[logs["service"].isin(CANDIDATES) & ~logs["service"].isin(exclude_services)].copy()
    err = lg["error"] if "error" in lg else pd.Series([None] * len(lg), index=lg.index)
    lg["text"] = [mask(extract_text(m, e)) for m, e in zip(lg["message"], err)]
    lg = lg[lg["text"] != ""]
    return lg[["t", "service", "text"]].sort_values("t", kind="stable").reset_index(drop=True)

# ---------------------------------------------------------------- encoders


class HashingEncoder:
    """Character n-gram hashing (comparison B). No vocabulary is fitted, so unseen words are represented."""

    def __init__(self):
        from sklearn.feature_extraction.text import HashingVectorizer
        self.vec = HashingVectorizer(analyzer="char_wb", ngram_range=(3, 5), n_features=2 ** 18,
                                     alternate_sign=False, norm="l2")

    def __call__(self, texts):
        return self.vec.transform(texts)


class MiniLMEncoder:
    """sentence-transformers all-MiniLM-L6-v2 at the pinned revision (comparisons C and D)."""
    NAME = "sentence-transformers/all-MiniLM-L6-v2"
    REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"

    def __init__(self, device=None, batch_size=256):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(self.NAME, revision=self.REVISION, device=device)
        self.model.max_seq_length = 256
        self.batch_size = batch_size

    def __call__(self, texts):
        return self.model.encode(list(texts), batch_size=self.batch_size, normalize_embeddings=True,
                                 convert_to_numpy=True, show_progress_bar=False)


class EmbeddingCache:
    """Vectors for unique texts, computed once and reused for every occurrence (PREREG 3)."""

    def __init__(self, encoder):
        self.encoder, self.index, self.rows = encoder, {}, []

    def ids(self, texts):
        new = [t for t in dict.fromkeys(texts) if t not in self.index]
        if new:
            for t in new:
                self.index[t] = len(self.index)
            self.rows.append(self.encoder(new))
        return np.fromiter((self.index[t] for t in texts), dtype=np.int64, count=len(texts))

    def matrix(self):
        if not self.rows:
            return np.zeros((0, 0))
        if hasattr(self.rows[0], "tocsr"):
            from scipy.sparse import vstack
            return vstack(self.rows).tocsr()
        return np.vstack(self.rows)

# ---------------------------------------------------------------- distances


def _max_cos(m, query_ids, ref_ids):
    """For each query id, max cosine similarity to the reference ids (rows are L2-normalised)."""
    if len(ref_ids) == 0:
        return np.full(len(query_ids), np.nan)
    q, r = m[query_ids], m[ref_ids]
    sims = q @ r.T
    sims = sims.toarray() if hasattr(sims, "toarray") else np.asarray(sims)
    return sims.max(axis=1)


def split_baseline(windows):
    """Reference period = first half of baseline_stats by time; distribution windows = those fully in the
    second half (PREREG 4.1). Returns (ref_start, ref_end, dist_windows)."""
    bs = windows[windows["label"] == "baseline_stats"]
    if bs.empty:
        return None, None, bs
    t0, t1 = float(bs["w_start"].min()), float(bs["w_end"].max())
    mid = (t0 + t1) / 2
    return t0, mid, bs[bs["w_start"] >= mid]


def _robust_delta(x, ref):
    med = np.nanmedian(ref)
    q1, q3 = np.nanpercentile(ref, [25, 75])
    iqr = q3 - q1
    return (x - med) / iqr if iqr != 0 else x - med


def semantic_features(logs, windows, cache, *, scope="service", prefix="f_lsem", n_min=5, m_min=20,
                      seed=20261116, services=CANDIDATES):
    """Per (window, service) features for one case.

    scope="service": reference = same service's first-half baseline logs (D, and B with a hashing cache).
    scope="all":     reference = all services' first-half baseline logs, randomly subsampled to the same
                     number of logs as that service's own reference (C).
    Returns columns w_start, service, <prefix>_dmean, <prefix>_dp90, <prefix>_valid.
    """
    ref_start, ref_end, dist_w = split_baseline(windows)
    out = []
    if ref_start is None:
        for s in services:
            out.append(pd.DataFrame({"w_start": windows["w_start"].to_numpy(), "service": s}))
        return _finish(pd.concat(out, ignore_index=True), prefix)
    lg = logs.copy()
    lg["id"] = cache.ids(lg["text"].tolist()) if len(lg) else np.zeros(0, dtype=np.int64)
    m = cache.matrix()
    in_ref = (lg["t"] >= ref_start) & (lg["t"] < ref_end)
    pool = lg.loc[in_ref, "id"].to_numpy()
    rng = np.random.default_rng(seed)
    starts, ends = windows["w_start"].to_numpy(), windows["w_end"].to_numpy()
    dist_set = set(dist_w["w_start"].to_numpy().tolist())

    for s in services:
        own = lg[lg["service"] == s]
        own_ref = own.loc[in_ref[own.index], "id"].to_numpy()
        frame = pd.DataFrame({"w_start": starts, "service": s,
                              "dmean": np.nan, "dp90": np.nan, "valid": 0})
        if len(own_ref) < m_min or len(own) == 0:
            out.append(frame)
            continue
        if scope == "service":
            ref_ids = np.unique(own_ref)
        elif scope == "all":
            take = rng.choice(len(pool), size=min(len(own_ref), len(pool)), replace=False)
            ref_ids = np.unique(pool[take])
        else:
            raise ValueError(scope)
        # Distances only for logs outside the reference period (no self-comparison).
        q = own[~in_ref[own.index]]
        uq = np.unique(q["id"].to_numpy())
        dist_of = dict(zip(uq.tolist(), (1.0 - _max_cos(m, uq, ref_ids)).tolist()))
        qt, qd = q["t"].to_numpy(), np.array([dist_of[i] for i in q["id"].to_numpy()])
        mean, p90 = np.full(len(starts), np.nan), np.full(len(starts), np.nan)
        for k, (a, b) in enumerate(zip(starts, ends)):
            if a < ref_end and b > ref_start:      # windows touching the reference period are not scored
                continue
            sel = (qt >= a) & (qt < b)
            if sel.sum() >= n_min:
                mean[k], p90[k] = qd[sel].mean(), np.percentile(qd[sel], 90)
        is_dist = np.array([w in dist_set for w in starts])
        ok_dist = is_dist & ~np.isnan(mean)
        if ok_dist.sum() < MIN_DIST_WINDOWS:
            out.append(frame)
            continue
        frame["dmean"] = _robust_delta(mean, mean[ok_dist])
        frame["dp90"] = _robust_delta(p90, p90[ok_dist])
        frame["valid"] = (~np.isnan(frame["dmean"].to_numpy())).astype(int)
        out.append(frame)
    return _finish(pd.concat(out, ignore_index=True), prefix)


def _finish(df, prefix):
    for c in ("dmean", "dp90"):
        if c not in df:
            df[c] = np.nan
    if "valid" not in df:
        df["valid"] = 0
    df.loc[df["dmean"].isna(), "valid"] = 0
    return df.rename(columns={"dmean": f"{prefix}_dmean", "dp90": f"{prefix}_dp90",
                              "valid": f"{prefix}_valid"})[
        ["w_start", "service", f"{prefix}_dmean", f"{prefix}_dp90", f"{prefix}_valid"]]


PREFIXES = {"B": "f_lchr", "C": "f_lsemall", "D": "f_lsem"}
