"""Window grid and RE2-OB lifecycle labels (docs/RE2OB-DECISIONS.md section 3-4)."""
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
