"""linux-v1 (self-collected) -> common long format. Interface only for now.

Implemented after the first formal pairs are available (B1 in docs/MILESTONES.md).
Same contract as features.adapters.re2ob (see features/adapters/__init__.py).

TODO when data exists:
- list_cases: read datasets/linux-v1/cases.parquet (one row per pair, eligible flags);
  Case.onset = effect_observed_at (pod_failure: first Ready=false), not the request time.
  Edge faults: Case.root_cause = "source->destination".
- load_metrics: runs/<run>/canonical-v2-*/metrics.parquet. Signals:
  cpu_cores = container_cpu_usage_rate (already cores, rate[60s]);
  cpu_limit_ratio = cpu_cores / kube_container_cpu_limit_cores;
  mem_limit_ratio = container_memory_working_set_bytes / kube_container_memory_limit_bytes;
  net_* from container_network_*_rate groups. Prometheus grid is already 5 s.
- load_spans: canonical-v2-*/traces.parquet (OTel spans). Map client/server spans the same
  way as RE2-OB: child span with parent in another service = one call on edge parent->child.
- load_logs: canonical-v2-*/logs.parquet, severity -> err. Remove service names, pod names
  and endpoints from any text-derived feature.
- Labels: label-schema.yaml lifecycle (warmup/boundary/transition/recovering excluded).
"""


def list_cases(root):
    raise NotImplementedError("linux-v1 adapter is implemented once formal pairs exist")


def load_metrics(case):
    raise NotImplementedError


def load_spans(case):
    raise NotImplementedError


def load_logs(case):
    raise NotImplementedError
