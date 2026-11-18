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
    # linux-v1 only (RE2-OB keeps the defaults). Times are Unix seconds; a control run carries
    # the sham times of its matched fault run (same onset offset and phase lengths).
    kind: str = "fault"                  # "fault" | "control"
    target_kind: str = "service_node"    # service_node | dependency_edge | workload_entrypoint
    pair_id: str = ""
    run_start: float | None = None
    injection: float | None = None       # injection_observed_at
    removal: float | None = None         # removal_observed_at
    recovery: float | None = None        # recovery_confirmed_at (None if not confirmed)
    eligible: bool = True                # data_valid and injection_valid and impact_confirmed
