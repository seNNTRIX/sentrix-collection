"""Retry attempts of a matched pair (runs/_campaign/<id>/decisions.yaml retry_pairs).

Run IDs are never reused. A pair whose collection failed is collected again
under new run IDs with an attempt suffix (-a2, -a3, ...); the failed attempt's
run folders and audit stay as they are. Each entry needs pair_id, attempt (>= 2),
failure_cause, failed_audit (the previous attempt's audit, which must exist and
be incomplete) and decided_on.

Dataset rule: a pair contributes at most ONE attempt. adopted_attempt() returns
the single valid attempt of a pair; earlier failed attempts are excluded with
their failure cause, and two valid attempts of one pair are refused.
"""
from pathlib import Path

RETRY_KEYS = ("pair_id", "attempt", "failure_cause", "failed_audit", "decided_on")
CHAOS_NAME_MAX = 63  # Kubernetes object name used by run-attended: <fault run id>-fault


def attempt_id(run_id, attempt):
    return run_id if attempt == 1 else f"{run_id}-a{attempt}"


def apply_retries(pairs, decisions, root, pair_status):
    """Return (pairs with retried run IDs, {pair_id: retry entry}).

    pair_status(fault_run_id) -> status.json dict or None."""
    entries = {}
    for entry in (decisions or {}).get("retry_pairs") or []:
        missing = [k for k in RETRY_KEYS if not (isinstance(entry, dict) and entry.get(k))]
        if missing:
            raise ValueError(f"retry_pairs entry {entry!r} lacks {missing}")
        if not isinstance(entry["attempt"], int) or entry["attempt"] < 2:
            raise ValueError(f"retry_pairs {entry['pair_id']}: attempt must be an integer >= 2")
        prior = entries.get(entry["pair_id"])
        if prior is None or entry["attempt"] > prior["attempt"]:
            entries[entry["pair_id"]] = entry
    out = []
    known = {p["pair_id"] for p in pairs}
    for pair_id in entries:
        if pair_id not in known:
            raise ValueError(f"retry_pairs {pair_id}: not in the schedule")
    for p in pairs:
        entry = entries.get(p["pair_id"])
        if entry is None:
            out.append(p)
            continue
        n = entry["attempt"]
        prev_fault = attempt_id(p["fault_run_id"], n - 1)
        if not (Path(root) / entry["failed_audit"]).is_dir():
            raise ValueError(f"retry_pairs {p['pair_id']}: failed_audit {entry['failed_audit']} not found")
        if Path(entry["failed_audit"]).name != "pair-" + prev_fault:
            raise ValueError(f"retry_pairs {p['pair_id']}: failed_audit must be audits/pair-{prev_fault}")
        prev = pair_status(prev_fault)
        if prev is None or prev.get("complete"):
            raise ValueError(f"retry_pairs {p['pair_id']}: attempt {n - 1} is not an incomplete audit; nothing to retry")
        fault_id, control_id = attempt_id(p["fault_run_id"], n), attempt_id(p["control_run_id"], n)
        if len(fault_id + "-fault") > CHAOS_NAME_MAX:
            raise ValueError(f"retry_pairs {p['pair_id']}: chaos name {fault_id}-fault exceeds {CHAOS_NAME_MAX} chars")
        superseded = [attempt_id(p[k], a) for a in range(1, n) for k in ("fault_run_id", "control_run_id")]
        out.append({**p, "fault_run_id": fault_id, "control_run_id": control_id, "attempt": n,
                    "superseded_run_ids": superseded})
    return out, entries


def adopted_attempt(attempts, is_valid):
    """attempts: [(attempt number, fault run id, control run id)] of one pair.

    Returns the one attempt whose pair is valid, or None; never two."""
    valid = [a for a in attempts if is_valid(a)]
    if len(valid) > 1:
        raise ValueError(f"pair has {len(valid)} valid attempts {[a[0] for a in valid]}; adopt one by hand")
    return valid[0] if valid else None
