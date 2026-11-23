"""Log embedding page for the exhibition demo scenarios (stored linux-v1 runs, repetition 2).

Same scenarios as the model-server replay demo (demo/demo-times-b-fold2.json):
  delay frontend->productcatalogservice, pod_failure paymentservice, cpu_saturation currencyservice, packet_loss
  recommendationservice->productcatalogservice.
Window per scenario: 60 s before onset and 120 s after onset. Input = data/r8-input (masked lines; the masking is
features/log_semantic.mask, PREREG R8 3). Vectors = the R8 MiniLM vectors (all-MiniLM-L6-v2 @ 1110a243, cached by
run_r8.py). One point = one (scenario, service, phase, masked text, error flag) with its line count; identical
texts share one vector, so no jitter is added. UMAP/t-SNE are fitted once on the union of the scenarios' texts so
positions are comparable across scenarios. Distance (after-onset points only) = cosine distance in the 384-d space
to the nearest same-service text seen before onset in the same scenario.

  .venv/bin/python experiments/20261124-r8-run/viz/build_demo_viz.py <plotly.js> <style.css> <out.html>
"""
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
LV1 = ROOT / "data" / "r8-input" / "linux-v1-v0"
WORK = ROOT / "data" / "r8-work" / "lv1"
BEFORE, AFTER = 60, 120
SEED = 20261116
SCENARIOS = [
    ("lv1_linux-v1-delay-front-product-r02", "네트워크 지연 · frontend → productcatalogservice"),
    ("lv1_linux-v1-pod-paymentservice-r02", "Pod 장애 · paymentservice"),
    ("lv1_linux-v1-cpu-currencyservice-r02-a2", "CPU 과부하 · currencyservice"),
    ("lv1_linux-v1-loss-recommendation-product-r02", "패킷 손실 · recommendationservice → productcatalogservice"),
]


def main(plotly_js, style_css, out_html):
    texts = pd.read_parquet(WORK / "texts.parquet").sort_values("text_id")
    assert (texts["text_id"].to_numpy() == np.arange(len(texts))).all()
    vec = np.load(WORK / "minilm.npy")
    meta = pd.read_parquet(LV1 / "cases-meta.parquet").set_index("case_id")
    rows, summary = [], []
    for sid, (cid, title) in enumerate(SCENARIOS):
        on = float(meta.loc[cid, "onset"])
        d = pd.read_parquet(LV1 / "logs" / f"{cid}.parquet")
        d = d[(d["t"] >= on - BEFORE) & (d["t"] < on + AFTER)].copy()
        d["service"] = d["service"].astype(str)
        d = d[d["text_id"].map(lambda i: texts["text"].iat[i] != "")]
        d["phase"] = np.where(d["t"] < on, "before", "after")
        d["rel"] = d["t"] - on
        g = d.groupby(["service", "phase", "text_id", "err"], observed=True).agg(count=("t", "size"), first=("rel", "min")).reset_index()
        g["scenario"] = sid
        rows.append(g)
        for s in sorted(d["service"].unique()):
            x = d[d["service"] == s]
            summary.append({"scenario": sid, "service": s, "before": int((x["phase"] == "before").sum()),
                            "after": int((x["phase"] == "after").sum())})
    P = pd.concat(rows, ignore_index=True)
    ids = np.sort(P["text_id"].unique())
    X = vec[ids]
    import umap
    from sklearn.manifold import TSNE
    u3 = umap.UMAP(n_components=3, metric="cosine", n_neighbors=15, min_dist=0.1, random_state=SEED).fit_transform(X)
    u2 = umap.UMAP(n_components=2, metric="cosine", n_neighbors=15, min_dist=0.1, random_state=SEED).fit_transform(X)
    t2 = TSNE(n_components=2, metric="cosine", perplexity=min(30, len(ids) - 1), init="pca", random_state=SEED,
              max_iter=1500).fit_transform(X)
    pos = {int(t): i for i, t in enumerate(ids)}
    points = []
    for r in P.itertuples(index=False):
        dist, novel = None, False
        if r.phase == "after":
            ref = P[(P["scenario"] == r.scenario) & (P["service"] == r.service) & (P["phase"] == "before")]["text_id"].unique()
            if len(ref):
                dist = float(max(0.0, 1.0 - (vec[ref] @ vec[r.text_id]).max()))
                novel = dist > 1e-6
        i = pos[int(r.text_id)]
        points.append({"id": len(points), "scenario": int(r.scenario), "service": r.service, "phase": r.phase,
                       "severity": "오류·경고" if int(r.err) == 1 else "일반", "count": int(r.count),
                       "time_s": round(float(r.first), 3), "text": texts["text"].iat[int(r.text_id)],
                       "distance": None if dist is None else round(dist, 4), "novel": bool(novel),
                       "umap3": [round(float(v), 4) for v in u3[i]], "umap2": [round(float(v), 4) for v in u2[i]],
                       "tsne2": [round(float(v), 4) for v in t2[i]]})
    services = sorted(P["service"].unique())
    data = {"meta": {"title": "SentriX 로그 임베딩 탐색 · 시연 사례", "before_seconds": BEFORE, "after_seconds": AFTER,
                     "scenarios": [{"id": i, "case_id": c, "title": t} for i, (c, t) in enumerate(SCENARIOS)],
                     "services": services, "lines": int(P["count"].sum()), "unique_texts": int(len(ids)),
                     "points": len(points), "dimension": int(vec.shape[1]),
                     "model": {"name": "sentence-transformers/all-MiniLM-L6-v2", "revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"},
                     "umap": {"n_neighbors": 15, "min_dist": 0.1}, "tsne": {"perplexity": min(30, len(ids) - 1)}, "seed": SEED},
            "points": points, "summary": summary}
    tpl = (Path(__file__).parent / "page.template.html").read_text(encoding="utf-8")
    html = (tpl.replace("/*STYLE*/", Path(style_css).read_text(encoding="utf-8"))
               .replace("/*PLOTLY*/", Path(plotly_js).read_text(encoding="utf-8"))
               .replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")))
    Path(out_html).write_text(html, encoding="utf-8")
    (Path(out_html).with_suffix(".json")).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: data["meta"][k] for k in ("lines", "unique_texts", "points")}),
          {s["title"]: int(P[P["scenario"] == s["id"]]["count"].sum()) for s in data["meta"]["scenarios"]})


if __name__ == "__main__":
    main(*sys.argv[1:4])
