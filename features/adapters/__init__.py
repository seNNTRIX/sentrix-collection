"""Data-source adapters. Each returns the same long-format frames.

Contract (every adapter):
  list_cases(root) -> list[Case]
  load_metrics(case) -> DataFrame[t, service, signal, value]   resampled to RESAMPLE_SECONDS
  load_spans(case)   -> DataFrame[t, dur_s, service, parent_service, parent_dur_s, err]
  load_logs(case)    -> DataFrame[t, service, err]
Times are Unix seconds (float). Service names are canonical (features.schema.CANDIDATES).
"""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Case:
    case_id: str
    root_cause: str      # canonical service name (or edge "a->b" for linux-v1 edge faults)
    fault: str
    repetition: int
    onset: float         # effect/injection time used for labels, Unix seconds
    path: Path
