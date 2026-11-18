"""Window grid and lifecycle labels (RE2-OB: docs/RE2OB-DECISIONS.md 3-4; linux-v1: docs/METHOD-FREEZE.md 5)."""
import math

import numpy as np
import pandas as pd

from features.schema import STRIDE_SECONDS, WINDOW_SECONDS

# RE2-OB lifecycle, seconds relative to injection.
RE2_BASELINE_STATS = (-720, -420)   # median/IQR source; its windows are not training rows
RE2_TRANSITION_END = 60             # windows overlapping [0, 60) are excluded


def make_windows(onset, t_min, t_max):
    """Half-open windows [start, start+WINDOW) aligned so that a window starts at onset."""
    first = onset + math.ceil((t_min - onset) / STRIDE_SECONDS) * STRIDE_SECONDS
    starts = np.arange(first, t_max - WINDOW_SECONDS + 1e-9, STRIDE_SECONDS)
    w = pd.DataFrame({"w_start": starts, "w_end": starts + WINDOW_SECONDS})
    w["rel"] = w["w_start"] - onset
    return w.reset_index(drop=True)


def label_re2ob(rel):
    """Label for a window starting `rel` seconds after injection."""
    end = rel + WINDOW_SECONDS
    lo, hi = RE2_BASELINE_STATS
    if rel >= lo and end <= hi:
        return "baseline_stats"
    if rel >= hi and end <= 0:
        return "normal"
    if rel >= RE2_TRANSITION_END:
        return "fault_active"
    if end > 0 and rel < RE2_TRANSITION_END:
        return "transition"
    return "excluded"


# linux-v1 lifecycle (frozen in R5), seconds relative to onset = effect_observed_at.
LV1_WARMUP = 180          # from run start
LV1_NORMAL_SPAN = 120     # [onset-120, onset) is normal; earlier baseline (after warmup) is baseline_stats


def label_linux_v1(rel, case):
    """Label for a window starting `rel` s after case.onset (fault or control run of linux-v1).

    warmup -> excluded; [warmup end, onset-120) -> baseline_stats; [onset-120, onset) -> normal (and before
    injection_observed_at); windows touching [injection, onset+60) -> transition; [onset+60, removal) ->
    fault_active (control: sham_active, a normal window); [removal, recovery) -> recovering;
    after recovery -> recovered (normal). Windows that cross a boundary get the later, excluded-type label.
    """
    start = case.onset + rel
    end = start + WINDOW_SECONDS
    warm_end = case.run_start + LV1_WARMUP
    inj = case.injection if case.injection is not None else case.onset
    if start < warm_end:
        return "excluded"
    if end <= case.onset - LV1_NORMAL_SPAN:
        return "baseline_stats"
    if start >= case.onset - LV1_NORMAL_SPAN and end <= min(case.onset, inj):
        return "normal"
    if start < case.onset - LV1_NORMAL_SPAN:
        return "excluded"                          # crosses the baseline_stats / normal boundary
    if rel < RE2_TRANSITION_END:
        return "transition"
    if case.removal is not None and end <= case.removal:
        return "sham_active" if case.kind == "control" else "fault_active"
    if case.recovery is not None and start >= case.recovery:
        return "recovered"
    return "recovering"
