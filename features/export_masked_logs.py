"""Masked linux-v1 logs and R8 input tables for the public repository (data/r8-input/linux-v1-v0/).

R8 (experiments/20261116-log-semantic-r8/PREREG.md) needs, per case, the log lines (t, service, text) and the
30 s window table (w_start, w_end, label). The raw log lines are never written: every line is reduced with the
R8 functions themselves, text = features.log_semantic.mask(features.log_semantic.extract_text(message, error))
(load_logs has no `error` column, so error = None exactly as in log_semantic.prepare_logs).
features/log_semantic.py is the unchanged file of log-semantic-r8 42ffbea (git blob 1aa0e40c...).

Steps (each a subcommand; run from the repository root with the dataset venv):
  export   logs/<case_id>.parquet  one row per load_logs line, in load_logs order (nothing dropped):
                                   case_id, row, t, service, text_id, err
           log-texts.parquet       text_id, text (unique masked texts, ids in first-seen order, cases sorted)
           windows.parquet         make_windows(onset, metric t_min, metric t_max + 1) + label_linux_v1, exactly as
                                   features/build_linux_v1.build_case; join key (case_id, meta_window) =
                                   (meta_case_id, meta_window) of ranking/detection/edges
           cases-meta.parquet      case_id, kind, fault, root_cause, repetition, eligible, onset, onset_source,
                                   removal, run_start, run_end (+ metric_t_min, metric_t_max: window inputs)
  tables   copies the feature tables, dropping string columns / JSON keys holding a local path, host name or IP
  check    reproduction check (line counts; prepare_logs + semantic_features B, scope service and all)
  scan     security scan of every string column of every output table

  python -m features.export_masked_logs export --out data/r8-input/linux-v1-v0
  python -m features.export_masked_logs tables --features data/features/linux-v1-v0 --out data/r8-input/linux-v1-v0
  python -m features.export_masked_logs check  --out data/r8-input/linux-v1-v0 --cases <id> <id> <id>
  python -m features.export_masked_logs scan   --out data/r8-input/linux-v1-v0 [--words <user names>]

Restoring R8 input from the published files (no raw data needed): see restore_logs / prepared_from_restored.
"""
import argparse
import getpass
import json
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from features.adapters import linux_v1
from features.log_semantic import extract_text, mask
from features.schema import CANDIDATES
from features.windows import label_linux_v1, make_windows

ROOTS = "campaigns/linux-v1/dataset-roots.yaml"
LOG_COLUMNS = ["case_id", "row", "t", "service", "text_id", "err"]
TABLES = ["ranking.parquet", "ranking-nodeview.parquet", "detection.parquet", "detection-ineligible.parquet",
          "edges.parquet", "cases.parquet", "folds.json", "build-summary.json"]
PARQUET = dict(compression="zstd", compression_level=19)


def case_windows(case, metrics=None):
    """Window table of one case, as build_linux_v1.build_case makes it."""
    metrics = linux_v1.load_metrics(case) if metrics is None else metrics
    t_min, t_max = metrics["t"].min(), metrics["t"].max()
    w = make_windows(case.onset, t_min, t_max + 1)
    w["label"] = w["rel"].map(lambda r: label_linux_v1(r, case))
    w = w.rename(columns={"rel": "meta_rel"})
    w.insert(0, "meta_window", np.arange(len(w), dtype=np.int32))
    w.insert(0, "case_id", case.case_id)
    return w[["case_id", "meta_window", "w_start", "w_end", "meta_rel", "label"]], float(t_min), float(t_max)


def masked_texts(logs):
    err = logs["error"] if "error" in logs else pd.Series([None] * len(logs), index=logs.index)
    return [mask(extract_text(m, e)) for m, e in zip(logs["message"], err)]


def run_end(case):
    rt = json.loads((case.path / "runtime.json").read_text(encoding="utf-8"))
    return float(case.run_start + float(rt["workload_elapsed_s"]))


def cmd_export(a):
    out = Path(a.out)
    (out / "logs").mkdir(parents=True, exist_ok=True)
    cases = sorted(linux_v1.list_cases(a.roots), key=lambda c: c.case_id)
    texts, wins, meta = {}, [], []
    for i, case in enumerate(cases, 1):
        t0 = time.time()
        lg = linux_v1.load_logs(case, keep_text=True)
        tx = masked_texts(lg)
        ids = np.fromiter((texts.setdefault(t, len(texts)) for t in tx), dtype=np.int32, count=len(tx))
        n = len(lg)
        table = pa.table({
            "case_id": pa.array([case.case_id] * n, pa.string()).dictionary_encode(),
            "row": pa.array(np.arange(n, dtype=np.int32)),
            "t": pa.array(lg["t"].to_numpy(dtype=np.float64)),
            "service": pa.array(lg["service"].to_numpy(), pa.string()).dictionary_encode(),
            "text_id": pa.array(ids),
            "err": pa.array(lg["err"].to_numpy(dtype=np.int8)),
        })
        pq.write_table(table, out / "logs" / f"{case.case_id}.parquet", **PARQUET)
        del lg, tx, table
        w, t_min, t_max = case_windows(case)
        wins.append(w)
        meta.append({"case_id": case.case_id, "kind": case.kind, "fault": case.fault, "root_cause": case.root_cause,
                     "repetition": int(case.repetition), "eligible": bool(case.eligible), "onset": float(case.onset),
                     "onset_source": case.onset_source, "removal": case.removal, "run_start": float(case.run_start),
                     "run_end": run_end(case), "metric_t_min": t_min, "metric_t_max": t_max, "n_log_lines": n})
        print(f"[{i}/{len(cases)}] {case.case_id}: {n} lines, {len(w)} windows, {len(texts)} texts so far, "
              f"{time.time() - t0:.1f}s", flush=True)
    pq.write_table(pa.table({"text_id": pa.array(np.arange(len(texts), dtype=np.int32)),
                             "text": pa.array(list(texts), pa.string())}), out / "log-texts.parquet", **PARQUET)
    pq.write_table(pa.Table.from_pandas(pd.concat(wins, ignore_index=True), preserve_index=False),
                   out / "windows.parquet", **PARQUET)
    pq.write_table(pa.Table.from_pandas(pd.DataFrame(meta), preserve_index=False), out / "cases-meta.parquet",
                   **PARQUET)
    print(f"done: {len(cases)} cases, {len(texts)} unique texts")


# ---------------------------------------------------------------- restore (public-side)

def restore_logs(out, case_id):
    """Log lines of one case from the published files: line table + text dictionary, sorted by row."""
    out = Path(out)
    lg = pd.read_parquet(out / "logs" / f"{case_id}.parquet")
    tx = pd.read_parquet(out / "log-texts.parquet")
    lg = lg.merge(tx, on="text_id", how="left", validate="many_to_one").sort_values("row", kind="stable")
    lg["case_id"], lg["service"] = lg["case_id"].astype(str), lg["service"].astype(str)
    return lg.reset_index(drop=True)


def prepared_from_restored(lg, exclude_services=()):
    """Same rows as log_semantic.prepare_logs on the raw lines (the text is already masked)."""
    lg = lg[lg["service"].isin(CANDIDATES) & ~lg["service"].isin(exclude_services)]
    lg = lg[lg["text"] != ""]
    return lg[["t", "service", "text"]].sort_values("t", kind="stable").reset_index(drop=True)


def restore_windows(out, case_id):
    w = pd.read_parquet(Path(out) / "windows.parquet", filters=[("case_id", "=", case_id)])
    return w.sort_values("meta_window").reset_index(drop=True)


# ---------------------------------------------------------------- tables

def sensitive_patterns(cases):
    hosts = sorted({c.root_name for c in cases} | {str(c.environment_id) for c in cases})
    return {
        "path": re.compile(r"(^|[\s\"'=(])(/home/|/Users/|/root/|/var/|/tmp/|~/|[A-Za-z]:\\)"),
        "host": re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, hosts)) + r")(?![\w-])"),
        "ipv4": re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b"),
    }


def _hit(value, pats):
    return [k for k, rx in pats.items() if isinstance(value, str) and rx.search(value)]


ALWAYS_DROP = {"$.excluded_attempts[].failure_cause"}   # free text about the collection PCs: dropped as a key


def _clean_json(obj, pats, path, dropped):
    if isinstance(obj, dict):
        res = {}
        for k, v in obj.items():
            p = f"{path}.{k}"
            if p in ALWAYS_DROP:
                dropped.append((p, "always"))
                continue
            if _hit(k, pats):
                dropped.append((p, "key:" + ",".join(_hit(k, pats))))
                continue
            if isinstance(v, str) and _hit(v, pats):
                dropped.append((p, ",".join(_hit(v, pats))))
                continue
            res[k] = _clean_json(v, pats, p, dropped)
        return res
    if isinstance(obj, list):
        return [_clean_json(v, pats, f"{path}[]", dropped) for v in obj]
    return obj


def cmd_tables(a):
    src, out = Path(a.features), Path(a.out)
    pats = sensitive_patterns(linux_v1.list_cases(a.roots))
    report = {}
    for name in TABLES:
        if name.endswith(".json"):
            dropped = []
            obj = _clean_json(json.loads((src / name).read_text(encoding="utf-8")), pats, "$", dropped)
            (out / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            report[name] = sorted({re.sub(r"\.(lv1_)?linux-v1[\w-]*", ".<run_id>", p) + " (" + k + ")"
                                   for p, k in dropped})
            continue
        df = pd.read_parquet(src / name)
        drop = {}
        for c in df.columns:
            if df[c].dtype == object or str(df[c].dtype) in ("string", "category"):
                kinds = sorted({k for v in df[c].dropna().astype(str).unique() for k in _hit(v, pats)})
                if kinds:
                    drop[c] = kinds
        if drop:
            pq.write_table(pa.Table.from_pandas(df.drop(columns=list(drop)), preserve_index=False), out / name,
                           **PARQUET)
        else:
            shutil.copyfile(src / name, out / name)      # unchanged: byte copy, same sha256 as the source
        report[name] = [f"{c} ({','.join(k)})" for c, k in drop.items()]
    print(json.dumps(report, indent=1, ensure_ascii=False))
    (out / "_tables-dropped.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n",
                                              encoding="utf-8")


# ---------------------------------------------------------------- check

def _features(prepared, windows):
    from features.log_semantic import EmbeddingCache, HashingEncoder, PREFIXES, semantic_features
    res = {}
    for scope in ("service", "all"):
        res[scope] = semantic_features(prepared, windows, EmbeddingCache(HashingEncoder()), scope=scope,
                                       prefix=PREFIXES["B"])
    return res


def cmd_check(a):
    out = Path(a.out)
    cases = {c.case_id: c for c in linux_v1.list_cases(a.roots)}
    meta = pd.read_parquet(out / "cases-meta.parquet").set_index("case_id")
    texts = pd.read_parquet(out / "log-texts.parquet")
    result = {"line_counts": {}, "cases": {}}
    # 1. line counts: every run, published rows = load_logs rows (raw read again) and rows 0..n-1
    bad = []
    for cid in sorted(cases):
        n_raw = len(linux_v1.load_logs(cases[cid], keep_text=False))
        f = pq.ParquetFile(out / "logs" / f"{cid}.parquet")
        rows = f.read(columns=["row", "text_id"])
        r = rows.column("row").to_numpy()
        ok = (f.metadata.num_rows == n_raw == int(meta.loc[cid, "n_log_lines"])
              and np.array_equal(r, np.arange(n_raw)) and rows.column("text_id").to_numpy().max() < len(texts))
        if not ok:
            bad.append(cid)
    result["line_counts"] = {"runs": len(cases), "mismatch": bad}
    print("line counts:", result["line_counts"], flush=True)
    # windows: label counts = cases.parquet windows_<label>; feature-table keys join with the same rel/label
    wall = pd.read_parquet(out / "windows.parquet")
    ct = pd.read_parquet(out / "cases.parquet").set_index("case_id")
    cnt = wall.groupby(["case_id", "label"]).size().unstack(fill_value=0)
    wbad = [cid for cid in ct.index if any(int(cnt.loc[cid].get(c[len("windows_"):], 0)) != int(ct.loc[cid, c])
                                           for c in ct.columns if c.startswith("windows_") and not
                                           pd.isna(ct.loc[cid, c]))]
    joins = {}
    for name in ("ranking.parquet", "ranking-nodeview.parquet", "detection.parquet", "detection-ineligible.parquet",
                 "edges.parquet"):
        ft = pd.read_parquet(out / name, columns=["meta_case_id", "meta_window", "meta_rel", "meta_label"])
        j = ft.merge(wall, left_on=["meta_case_id", "meta_window"], right_on=["case_id", "meta_window"],
                     how="left", suffixes=("", "_w"))
        joins[name] = {"rows": len(ft), "unmatched": int(j["w_start"].isna().sum()),
                       "rel_or_label_differs": int(((j["meta_rel"] != j["meta_rel_w"])
                                                    | (j["meta_label"] != j["label"])).sum())}
    result["windows"] = {"rows": len(wall), "label_count_mismatch": wbad, "feature_table_join": joins}
    print("windows:", result["windows"], flush=True)
    bad = bad + wbad + [n for n, v in joins.items() if v["unmatched"] or v["rel_or_label_differs"]]
    # 2. features from raw vs from published, sample cases
    for cid in a.cases:
        case = cases[cid]
        raw = linux_v1.load_logs(case, keep_text=True)
        from features.log_semantic import prepare_logs
        prep_raw = prepare_logs(raw)
        w_raw, _, _ = case_windows(case)
        lg = restore_logs(out, cid)
        same_lines = (np.array_equal(lg["t"].to_numpy(), raw["t"].to_numpy())
                      and (lg["service"].to_numpy() == raw["service"].to_numpy()).all()
                      and np.array_equal(lg["err"].to_numpy(), raw["err"].to_numpy())
                      and lg["text"].tolist() == masked_texts(raw))
        prep_pub = prepared_from_restored(lg)
        w_pub = restore_windows(out, cid)
        rec = {"fault": case.fault, "kind": case.kind, "lines": len(raw), "prepared_rows": len(prep_raw),
               "windows": len(w_raw), "lines_equal": bool(same_lines)}
        try:
            pd.testing.assert_frame_equal(prep_raw, prep_pub, check_exact=True)
            rec["prepared_equal"] = True
        except AssertionError as e:
            rec["prepared_equal"] = False
            rec["prepared_diff"] = str(e)[:300]
        try:
            pd.testing.assert_frame_equal(w_raw, w_pub, check_exact=True, check_dtype=False,
                                          check_categorical=False)
            rec["windows_equal"] = True
        except AssertionError as e:
            rec["windows_equal"] = False
            rec["windows_diff"] = str(e)[:300]
        fr, fp = _features(prep_raw, w_raw), _features(prep_pub, w_pub)
        for scope in ("service", "all"):
            x, y = fr[scope], fp[scope]
            num = [c for c in x.columns if c.startswith("f_")]
            try:
                pd.testing.assert_frame_equal(x, y, check_exact=True)
                eq = True
            except AssertionError:
                eq = False
            nan_same = all(np.array_equal(x[c].isna().to_numpy(), y[c].isna().to_numpy()) for c in num)
            rec[f"B_{scope}"] = {"equal": eq, "nan_positions_equal": nan_same, "rows": len(x),
                                 "valid_rows": int(x[f"f_lchr_valid"].sum()),
                                 "nan_dmean": int(x["f_lchr_dmean"].isna().sum())}
        result["cases"][cid] = rec
        print(cid, json.dumps(rec), flush=True)
    passed = (not bad) and all(r["lines_equal"] and r["prepared_equal"] and r["windows_equal"]
                               and r["B_service"]["equal"] and r["B_all"]["equal"] for r in result["cases"].values())
    result["passed"] = bool(passed)
    (out / "_check.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print("PASS" if passed else "FAIL")
    if not passed:
        sys.exit(1)


# ---------------------------------------------------------------- scan

def scan_patterns(cases, words):
    hosts = sorted({c.root_name for c in cases} | {str(c.environment_id) for c in cases})
    users = sorted(set(words) | {getpass.getuser()})
    return {
        "ipv4": re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b"),
        "ipv6": re.compile(r"(?<![\w:])(([0-9a-f]{1,4}:){2,7}[0-9a-f]{1,4}|([0-9a-f]{1,4}:){1,7}:([0-9a-f]{1,4})?"
                           r"|::([0-9a-f]{1,4}:){0,6}[0-9a-f]{1,4})(?![\w:])", re.I),
        "node_host": re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, hosts)) + r")(?![\w-])"),
        "pod_name": re.compile(r"\b[a-z0-9]+(-[a-z0-9]+)*-[a-z0-9]{8,10}-[a-z0-9]{5}\b"),
        "uuid": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),
        "email": re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"),
        "user_name": re.compile(r"(?i)\b(" + "|".join(map(re.escape, users)) + r")\b"),
        "abs_path": re.compile(r"(/home/|/Users/|[A-Za-z]:\\)"),
        "digits8": re.compile(r"\d{8,}"),
    }


def _string_values(path):
    """{column: unique string values} of a parquet table or a JSON file (all string leaves)."""
    if path.suffix == ".json":
        vals = {}

        def walk(o, keys):
            if isinstance(o, dict):
                for k, v in o.items():
                    vals.setdefault("<json key>", set()).add(str(k))
                    walk(v, keys + (str(k),))
            elif isinstance(o, list):
                for v in o:
                    walk(v, keys)
            elif isinstance(o, str):
                vals.setdefault("/".join(keys), set()).add(o)
        walk(json.loads(path.read_text(encoding="utf-8")), ())
        return vals
    t = pq.read_table(path)
    res = {}
    for name in t.column_names:
        col = t.column(name)
        if pa.types.is_dictionary(col.type):
            col = col.cast(col.type.value_type)
        if pa.types.is_string(col.type) or pa.types.is_large_string(col.type):
            res[name] = set(col.drop_null().unique().to_pylist())
    return res


# Scan exceptions (decided 2026-11-23, README "보안 검사"):
#  1. hexadecimal memory addresses starting with 0x (Go pointers left by log_semantic.mask), in any column
#  2. hexadecimal hash values in columns / JSON keys named view, *_commit, *_sha256 (reproduction records)
GO_POINTER = re.compile(r"0x[0-9a-f]+")
HASH_COLUMN = re.compile(r"(^|/)(view|[\w.-]*_commit|[\w.-]*_sha256)(/|$)")
HEX_HASH = re.compile(r"[0-9a-f]{7,64}")


def apply_exceptions(col, value, counts):
    v = GO_POINTER.sub("", value)
    if v != value:
        counts["go_pointer_0x"] += 1
    if HASH_COLUMN.search(col):
        w = HEX_HASH.sub("", v)
        if w != v:
            counts["hash_in_view_commit_sha256"] += 1
        v = w
    return v


def cmd_scan(a):
    out = Path(a.out)
    pats = scan_patterns(linux_v1.list_cases(a.roots), a.words)
    files = sorted(p for p in out.rglob("*") if p.suffix in (".parquet", ".json") and not p.name.startswith("_"))
    hits = {k: {"count": 0, "examples": []} for k in pats}
    exempt = {"go_pointer_0x": 0, "hash_in_view_commit_sha256": 0}
    for p in files:
        for col, vals in _string_values(p).items():
            for v in vals:
                v = apply_exceptions(col, v, exempt)
                for k, rx in pats.items():
                    m = rx.search(v)
                    if m:
                        hits[k]["count"] += 1
                        if len(hits[k]["examples"]) < 5:
                            hits[k]["examples"].append({"file": str(p.relative_to(out)), "column": col,
                                                        "match": m.group(0), "value": v[:160]})
    res = {"files": len(files), "patterns": {k: rx.pattern for k, rx in pats.items() if k not in ("node_host",
                                                                                                  "user_name")},
           "exceptions_applied": exempt, "hits": hits, "passed": all(h["count"] == 0 for h in hits.values())}
    print(json.dumps(res, indent=1, ensure_ascii=False))
    (out / "_scan.json").write_text(json.dumps({k: v for k, v in res.items()}, indent=1, ensure_ascii=False) + "\n",
                                    encoding="utf-8")
    if not res["passed"]:
        sys.exit(1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["export", "tables", "check", "scan"])
    ap.add_argument("--roots", default=ROOTS)
    ap.add_argument("--features", default="data/features/linux-v1-v0")
    ap.add_argument("--out", default="data/r8-input/linux-v1-v0")
    ap.add_argument("--cases", nargs="*", default=[])
    ap.add_argument("--words", nargs="*", default=[], help="extra user names to scan for")
    a = ap.parse_args(argv)
    {"export": cmd_export, "tables": cmd_tables, "check": cmd_check, "scan": cmd_scan}[a.step](a)


if __name__ == "__main__":
    main()
