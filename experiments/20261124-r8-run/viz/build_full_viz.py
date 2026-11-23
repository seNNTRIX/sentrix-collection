"""Log embedding page over the whole linux-v1 R8 log set (138 runs: 69 fault + 69 control).

Input = data/r8-input (masked lines; masking = features/log_semantic.mask, PREREG R8 3). Vectors = R8 MiniLM vectors
(all-MiniLM-L6-v2 @ 1110a243, cached by run_r8.py). Phase per run: before = [run_start+180, onset), during =
[onset, removal), after = [removal, run_end); control runs use the sham onset/removal of their fault pair.
One point = one (fault type, service, phase, masked text, error flag) with its line count; identical texts share one
vector (no jitter). UMAP/t-SNE are fitted on all unique texts. "New" = the text never appears for that service in the
before phase of any run; distance = cosine distance (384-d) to the nearest same-service before-phase text.

  .venv/bin/python experiments/20261124-r8-run/viz/build_full_viz.py <plotly.js> <style.css> <out.html>
"""
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
LV1 = ROOT / "data" / "r8-input" / "linux-v1-v0"
WORK = ROOT / "data" / "r8-work" / "lv1"
WARMUP, SEED = 180, 20261116
FAULT_NAME = {"cpu_saturation": "CPU 과부하", "pod_failure": "Pod 장애", "network_delay": "네트워크 지연",
              "packet_loss": "패킷 손실", "load_surge": "부하 급증", "control": "대조 (장애 없음)"}


def fault_key(row):
    if row["kind"] == "control":
        return "control"
    return row["fault"] if row["fault"] in FAULT_NAME else ("load_surge" if "surge" in str(row["fault"]) else row["fault"])


def main(plotly_js, style_css, out_html):
    texts = pd.read_parquet(WORK / "texts.parquet").sort_values("text_id")["text"].tolist()
    vec = np.load(WORK / "minilm.npy")
    meta = pd.read_parquet(LV1 / "cases-meta.parquet")
    parts, dur = [], {}
    for _, c in meta.iterrows():
        d = pd.read_parquet(LV1 / "logs" / f"{c['case_id']}.parquet", columns=["t", "service", "text_id", "err"])
        lo = c["run_start"] + WARMUP
        d = d[(d["t"] >= lo) & (d["t"] < c["run_end"])]
        d = d[[texts[i] != "" for i in d["text_id"].to_numpy()]]
        phase = np.where(d["t"] < c["onset"], "before", np.where(d["t"] < c["removal"], "during", "after"))
        fk = fault_key(c)
        g = pd.DataFrame({"fault": fk, "service": d["service"].astype(str).to_numpy(), "phase": phase,
                          "text_id": d["text_id"].to_numpy(), "err": d["err"].to_numpy()})
        parts.append(g.groupby(["fault", "service", "phase", "text_id", "err"]).size().rename("count").reset_index())
        for ph, a, b in (("before", lo, c["onset"]), ("during", c["onset"], c["removal"]), ("after", c["removal"], c["run_end"])):
            dur[(fk, ph)] = dur.get((fk, ph), 0.0) + max(0.0, float(b - a))
        print(c["case_id"], len(d), flush=True)
    P = pd.concat(parts).groupby(["fault", "service", "phase", "text_id", "err"], as_index=False)["count"].sum()
    ids = np.sort(P["text_id"].unique())
    import umap
    from sklearn.manifold import TSNE
    X = vec[ids]
    u3 = umap.UMAP(n_components=3, metric="cosine", n_neighbors=15, min_dist=0.1, random_state=SEED).fit_transform(X)
    u2 = umap.UMAP(n_components=2, metric="cosine", n_neighbors=15, min_dist=0.1, random_state=SEED).fit_transform(X)
    t2 = TSNE(n_components=2, metric="cosine", perplexity=30, init="pca", random_state=SEED, max_iter=1500).fit_transform(X)
    pos = {int(t): i for i, t in enumerate(ids)}
    ref = {s: np.unique(g["text_id"].to_numpy()) for s, g in P[P["phase"] == "before"].groupby("service")}
    points = []
    for r in P.itertuples(index=False):
        rs = ref.get(r.service)
        dist = None if rs is None or len(rs) == 0 else float(max(0.0, 1.0 - (vec[rs] @ vec[r.text_id]).max()))
        i = pos[int(r.text_id)]
        points.append({"id": len(points), "fault": r.fault, "service": r.service, "phase": r.phase,
                       "severity": "오류·경고" if int(r.err) == 1 else "일반", "count": int(r.count),
                       "t": int(r.text_id), "distance": None if dist is None else round(dist, 4),
                       "novel": bool(dist is not None and dist > 1e-6),
                       "umap3": [round(float(v), 3) for v in u3[i]], "umap2": [round(float(v), 3) for v in u2[i]],
                       "tsne2": [round(float(v), 3) for v in t2[i]]})
    summary = (P.groupby(["fault", "service", "phase"])["count"].sum().reset_index()
                .assign(seconds=lambda x: [dur[(f, p)] for f, p in zip(x["fault"], x["phase"])]))
    faults = [f for f in FAULT_NAME if f in set(P["fault"])]
    data = {"meta": {"faults": [{"key": f, "name": FAULT_NAME[f], "runs": int(sum(fault_key(c) == f for _, c in meta.iterrows()))} for f in faults],
                     "services": sorted(P["service"].unique()), "runs": int(len(meta)), "lines": int(P["count"].sum()),
                     "unique_texts": int(len(ids)), "points": len(points), "dimension": int(vec.shape[1]),
                     "model": {"name": "sentence-transformers/all-MiniLM-L6-v2", "revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"},
                     "umap": {"n_neighbors": 15, "min_dist": 0.1}, "tsne": {"perplexity": 30}, "seed": SEED},
            "texts": {str(int(t)): texts[int(t)] for t in ids}, "points": points,
            "summary": summary.to_dict(orient="records")}
    tpl = (Path(__file__).parent / "page-full.template.html").read_text(encoding="utf-8")
    html = (tpl.replace("/*STYLE*/", Path(style_css).read_text(encoding="utf-8"))
               .replace("/*PLOTLY*/", Path(plotly_js).read_text(encoding="utf-8"))
               .replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")))
    Path(out_html).write_text(html, encoding="utf-8")
    print(json.dumps({k: data["meta"][k] for k in ("runs", "lines", "unique_texts", "points")}),
          {f["name"]: f["runs"] for f in data["meta"]["faults"]})


if __name__ == "__main__":
    main(*sys.argv[1:4])
