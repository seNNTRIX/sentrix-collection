"""Poster tables and figures from the committed experiment results.

  .venv-r6/Scripts/python scripts/make_poster_figures.py --out docs/poster/re2ob

Reads (no training, no re-evaluation):
  experiments/20261027-re2ob-baselines/results.json          random (R3)
  experiments/20261027-re2ob-baselines/rcaeval_baro_official.json   BARO, RCAEval official protocol
  experiments/20261027-re2ob-r6-models/results.json, parts/  SentriX-model (rf|rel|pure), detection (lgbm|all|pure), stat
  experiments/20261027-re2ob-r7-raw-ablation/results.json    ablation (raw18 -> core35 -> rel18)
  data/features/re2ob-v0/detection.parquet                    only for the ROC curve (skipped if missing)

Writes PNG (300 dpi), CSV and values.json with every number drawn, so each figure can be traced back.
linux-v1: after the linux-v1 evaluation exists, add a loader that returns the same dict shapes and call the
same draw_* functions with dataset="linux-v1".
"""
import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

EXP = Path("experiments")
R3 = EXP / "20261027-re2ob-baselines"
R6 = EXP / "20261027-re2ob-r6-models"
R7 = EXP / "20261027-re2ob-r7-raw-ablation"

# reference palette (light), validated: blue / orange / aqua; aqua < 3:1 on white -> values are labelled
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
GRAY, INK, INK2, GRID = "#a8a6a0", "#0b0b0b", "#52514e", "#e6e5e1"
LABEL_BOX = {"boxstyle": "round,pad=0.12", "fc": "white", "ec": "none"}   # keeps value labels legible over the dashed line
FAULT_KO = {"cpu": "CPU", "mem": "메모리", "disk": "디스크", "delay": "지연", "loss": "패킷 손실", "socket": "소켓"}
MODEL_KO = {"logreg": "로지스틱 회귀", "rf": "Random Forest", "lgbm": "LightGBM", "xgb": "XGBoost", "catboost": "CatBoost"}


def style():
    plt.rcParams.update({
        "font.family": "Malgun Gothic", "axes.unicode_minus": False, "font.size": 11,
        "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y",
        "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True, "savefig.dpi": 300,
        "savefig.bbox": "tight", "figure.facecolor": "white"})


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ci_err(v):
    lo, hi = v["Avg@5_ci95"]
    return [[v["Avg@5"] - lo], [hi - v["Avg@5"]]]


def stat_line(ax, value, label):
    ax.axhline(value, color=INK2, linestyle=(0, (4, 3)), linewidth=1.2, zorder=1)
    ax.text(ax.get_xlim()[1], value, f" {label} {value:.3f}", va="center", ha="left", color=INK2, fontsize=10)


# ---------------------------------------------------------------- data
def collect():
    r3, baro, r6, r7 = load(R3 / "results.json"), load(R3 / "rcaeval_baro_official.json"), load(R6 / "results.json"), load(R7 / "results.json")
    rnd = r3["ranking"]["all_cases_all_candidates"]["random"]
    keys = ("AC@1", "AC@3", "Avg@5")
    pick, stat = "rf|rel|pure", "stat_combined"
    table = {
        "random": {"rep": {k: rnd[k] for k in keys}, "loso": {k: rnd[k] for k in keys}, "AUROC": None},
        "BARO": {"rep": {k: baro["dedup"][k] for k in keys}, "loso": {k: baro["dedup"][k] for k in keys}, "AUROC": None},
        "통계 방법": {"rep": {k: r6["ranking_rep"][stat][k] for k in keys}, "loso": {k: r6["ranking_loso"][stat][k] for k in keys},
                  "AUROC": r6["detection"]["stat_metric"]["AUROC"]},
        "SentriX-model": {"rep": {k: r6["ranking_rep"][pick][k] for k in keys}, "loso": {k: r6["ranking_loso"][pick][k] for k in keys},
                          "AUROC": r6["detection"]["lgbm|all|pure"]["AUROC"]},
    }
    ablation = [("원래 값\n(기본 모델)", r7["ranking"]["rf|raw18|loso"]),
                ("+ 자기 기준 정규화", r7["ranking"]["rf|core35|loso"]),
                ("+ 수준 값 제거\n(SentriX-model)", r7["ranking"]["rf|rel18|loso"])]
    models = {m: {fs: r6["ranking_loso"][f"{m}|{fs}|pure"] for fs in ("rel", "core", "all")} for m in MODEL_KO}
    faults = {"SentriX-model": r6["ranking_loso"][pick]["by_fault"], "통계 방법": r6["ranking_loso"][stat]["by_fault"]}
    return {"table": table, "ablation": ablation, "models": models, "faults": faults,
            "stat_loso_avg5": r6["ranking_loso"][stat]["Avg@5"]}


# ---------------------------------------------------------------- outputs
def write_table(d, out, dataset):
    cols = list(d["table"])
    rows = [("원인 서비스 · 본 서비스", "AC@1", "rep"), ("", "AC@3", "rep"), ("", "Avg@5", "rep"),
            ("원인 서비스 · 처음 보는 서비스", "AC@1", "loso"), ("", "AC@3", "loso"), ("", "Avg@5", "loso"),
            ("장애 탐지", "AUROC", None)]
    cells = []
    for grp, metric, split in rows:
        vals = [d["table"][c][split][metric] if split else d["table"][c]["AUROC"] for c in cols]
        cells.append((grp, metric, vals))
    with open(out / "table_main.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["구분", "지표"] + cols)
        for grp, metric, vals in cells:
            w.writerow([grp, metric] + ["" if v is None else f"{v:.3f}" for v in vals])

    fig, ax = plt.subplots(figsize=(8.6, 3.4))
    ax.axis("off")
    text = [[grp, metric] + ["—" if v is None else f"{v:.3f}" for v in vals] for grp, metric, vals in cells]
    t = ax.table(cellText=text, colLabels=["구분", "지표"] + cols, loc="center", cellLoc="center")
    t.auto_set_font_size(False)
    t.set_fontsize(10.5)
    t.scale(1, 1.55)
    for (r, c), cell in t.get_celld().items():
        cell.set_edgecolor(GRID)
        if r == 0:
            cell.set_facecolor("#f3f2ef")
            cell.set_text_props(weight="bold", color=INK)
        elif c >= 2:
            vals = [v for v in cells[r - 1][2] if v is not None]
            v = cells[r - 1][2][c - 2]
            if v is not None and v == max(vals):
                cell.set_text_props(weight="bold", color=INK)
        if c == len(cols) + 1 and r > 0:
            cell.set_facecolor("#eef4fc")
    t.auto_set_column_width(list(range(len(cols) + 2)))
    ax.set_title(f"원인 분석 성능 비교 ({dataset} 90 case)", color=INK, fontsize=13, pad=6)
    fig.text(0.01, -0.02, "학습이 없는 방법(random, BARO, 통계 방법)은 두 기준에서 값이 같다. BARO는 RCAEval 공식 프로토콜. 굵게 = 행 최고값.",
             fontsize=8.5, color=INK2)
    fig.savefig(out / "table_main.png")
    plt.close(fig)


def draw_ablation(d, out, dataset):
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    labels = [a for a, _ in d["ablation"]]
    vals = [v["Avg@5"] for _, v in d["ablation"]]
    colors = [GRAY, GRAY, BLUE]
    x = np.arange(len(vals))
    for i, (v, c) in enumerate(zip(vals, colors)):
        ax.bar(x[i], v, width=0.56, color=c, zorder=2)
        ax.errorbar(x[i], v, yerr=ci_err(d["ablation"][i][1]), color=INK2, capsize=4, linewidth=1.2, zorder=3)
        ax.text(x[i], d["ablation"][i][1]["Avg@5_ci95"][1] + 0.015, f"{v:.3f}", ha="center", va="bottom",
                color=INK, fontsize=12, weight="bold" if i == 2 else "normal", bbox=LABEL_BOX, zorder=4)
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 1.08)
    ax.set_xlim(-0.5, len(vals) - 0.5)
    ax.set_ylabel("Avg@5 (처음 보는 서비스)")
    stat_line(ax, d["stat_loso_avg5"], "통계 방법")
    ax.set_title(f"기본 모델 + SentriX 처리의 효과 ({dataset}, Random Forest)", color=INK, fontsize=12.5, loc="left")
    fig.text(0.01, -0.03, "막대 = LOSO Avg@5, 오차 막대 = case bootstrap 95% 신뢰구간", fontsize=8.5, color=INK2)
    fig.savefig(out / "fig_ablation.png")
    plt.close(fig)


def draw_models(d, out, dataset):
    fig, ax = plt.subplots(figsize=(8.6, 4.4))
    names = list(d["models"])
    sets = [("rel", "변화량 18개 (SentriX)", BLUE), ("core", "변화량 + 수준 값 35개", ORANGE), ("all", "전부 67개", AQUA)]
    x = np.arange(len(names))
    w = 0.26
    for j, (fs, label, color) in enumerate(sets):
        vals = [d["models"][m][fs]["Avg@5"] for m in names]
        pos = x + (j - 1) * w
        ax.bar(pos, vals, width=w - 0.03, color=color, label=label, zorder=2)
        for p, m in zip(pos, names):
            v = d["models"][m][fs]
            ax.errorbar(p, v["Avg@5"], yerr=ci_err(v), color=INK2, capsize=2.5, linewidth=0.9, zorder=3)
            ax.text(p, v["Avg@5_ci95"][1] + 0.012, f"{v['Avg@5']:.2f}", ha="center", va="bottom", fontsize=8, color=INK,
                    bbox=LABEL_BOX, zorder=4)
    ax.set_xticks(x, [MODEL_KO[m] for m in names])
    ax.set_ylim(0, 1.1)
    ax.set_xlim(-0.6, len(names) - 0.4)
    ax.set_ylabel("Avg@5 (처음 보는 서비스)")
    stat_line(ax, d["stat_loso_avg5"], "통계 방법")
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.1), ncol=3, frameon=False, fontsize=9.5)
    ax.set_title(f"모델 5종 × 입력 3종 비교 ({dataset})", color=INK, fontsize=12.5, loc="left")
    fig.savefig(out / "fig_models.png")
    plt.close(fig)


def draw_faults(d, out, dataset):
    fig, ax = plt.subplots(figsize=(8.0, 4.0))
    faults = list(d["faults"]["SentriX-model"])
    x = np.arange(len(faults))
    w = 0.36
    for j, (name, color) in enumerate((("SentriX-model", BLUE), ("통계 방법", ORANGE))):
        vals = [d["faults"][name][f] for f in faults]
        pos = x + (j - 0.5) * w
        ax.bar(pos, vals, width=w - 0.03, color=color, label=name, zorder=2)
        for p, v in zip(pos, vals):
            ax.text(p, v + 0.012, f"{v:.2f}", ha="center", va="bottom", fontsize=8.5, color=INK)
    ax.set_xticks(x, [FAULT_KO.get(f, f) for f in faults])
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("Avg@5 (처음 보는 서비스)")
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.1), ncol=2, frameon=False, fontsize=9.5)
    ax.set_title(f"장애 종류별 원인 순위 정확도 ({dataset})", color=INK, fontsize=12.5, loc="left")
    fig.savefig(out / "fig_faults.png")
    plt.close(fig)


def draw_roc(out, dataset, features):
    import pandas as pd
    from sklearn.metrics import roc_auc_score, roc_curve
    path = Path(features) / "detection.parquet"
    if not path.exists():
        print("skip ROC: missing", path)
        return None
    D = pd.read_parquet(path)
    y = D["target"].to_numpy()
    sentrix = np.array(load(R6 / "parts" / "lgbm.json")["detection"]["all"]["scores"], dtype=float)
    stat = D[[f"f_cm_{s}_dmean__max" for s in ("cpu_cores", "cpu_limit_ratio", "mem_limit_ratio",
                                                 "net_rx_pkts", "net_tx_pkts", "net_drop_pkts")]].max(axis=1).to_numpy()
    stat = np.where(np.isnan(stat), np.nanmin(stat) - 1, stat)
    fig, ax = plt.subplots(figsize=(4.8, 4.6))
    ax.grid(axis="both")
    aucs = {}
    for name, s, color in (("SentriX-model", sentrix, BLUE), ("통계 방법", stat, ORANGE)):
        fpr, tpr, _ = roc_curve(y, s)
        aucs[name] = float(roc_auc_score(y, s))
        ax.plot(fpr, tpr, color=color, linewidth=2, label=f"{name} (AUROC {aucs[name]:.3f})", zorder=3)
    ax.plot([0, 1], [0, 1], color=GRAY, linestyle=(0, (4, 3)), linewidth=1, zorder=2)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.01)
    ax.set_xlabel("오경보율 (FPR)")
    ax.set_ylabel("탐지율 (TPR)")
    ax.legend(loc="lower right", frameon=False, fontsize=9.5)
    ax.set_title(f"장애 탐지 ROC ({dataset}, window 단위)", color=INK, fontsize=12, loc="left")
    fig.savefig(out / "fig_detection_roc.png")
    plt.close(fig)
    return aucs


def main():
    global R6, R7
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="docs/poster/re2ob")
    ap.add_argument("--features", default="data/features/re2ob-v0")
    ap.add_argument("--r6", default=str(R6), help="R6 results folder (results.json, parts/)")
    ap.add_argument("--r7", default=str(R7), help="R7 results folder (results.json)")
    args = ap.parse_args()
    R6, R7 = Path(args.r6), Path(args.r7)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    style()
    dataset = "RE2-OB"
    d = collect()
    write_table(d, out, dataset)
    draw_ablation(d, out, dataset)
    draw_models(d, out, dataset)
    draw_faults(d, out, dataset)
    roc = draw_roc(out, dataset, args.features)
    values = {"dataset": dataset, "table": d["table"],
              "ablation": {k.replace("\n", " "): {"Avg@5": v["Avg@5"], "ci95": v["Avg@5_ci95"]} for k, v in d["ablation"]},
              "models_loso_avg5": {m: {fs: v["Avg@5"] for fs, v in d["models"][m].items()} for m in d["models"]},
              "faults_loso_avg5": d["faults"], "stat_loso_avg5": d["stat_loso_avg5"], "roc_auroc": roc}
    (out / "values.json").write_text(json.dumps(values, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    print("wrote", sorted(p.name for p in out.iterdir()))


if __name__ == "__main__":
    main()
