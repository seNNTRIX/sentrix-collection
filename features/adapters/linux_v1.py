"""linux-v1 (self-collected) -> common long format. Interface only; implemented once formal pairs exist.

Same contract as features.adapters.re2ob (features/adapters/__init__.py). The method is frozen in
docs/METHOD-FREEZE.md; this adapter may only translate data, never change features, windows,
labels, aggregation or models. Anything decided here must be written down before looking at
any linux-v1 result (METHOD-FREEZE.md section 6).

Interface
  list_cases(root) -> list[Case]
      One Case per fault run AND one per matched control run (kind="control", same pair_id,
      sham times copied from the fault run). Fields:
        onset      = effect_observed_at (pod_failure: first Ready=false; traffic_surge: surge start)
        injection  = injection_observed_at, removal = removal_observed_at,
        recovery   = recovery_confirmed_at or None, run_start = run_started_at
        root_cause = canonical service (service_node), "src->dst" (dependency_edge),
                     "workload->frontend" (workload_entrypoint)
        fault      = cpu_saturation | pod_failure | network_delay | packet_loss | traffic_surge
        repetition = 1..3 (fold = repetition), eligible = data_valid and injection_valid and impact_confirmed
  load_metrics(case) -> DataFrame[t, service, signal, value]   5 s grid, signals = schema.METRIC_SIGNALS
  load_spans(case)   -> DataFrame[t, dur_s, service, parent_service, parent_dur_s, err]
  load_logs(case)    -> DataFrame[t, service, err]             (not used by the frozen models)
  Labels: features.windows.label_linux_v1(rel, case).

TODO when data exists (in this order)
1. Read datasets/linux-v1 case/pair tables; map run ids to Case; check 69 fault + 69 control runs,
   eligible flags, and that every time field is present. Report missing ones; do not impute.
2. Metrics (canonical-v2-*/metrics.parquet), per pod -> canonical service (strip pod hash; redis-cart):
   cpu_cores        = rate of container_cpu_usage_seconds_total. Use the raw counter on the 5 s grid
                      (difference / 5 s, counter resets handled) if it was stored; otherwise the stored
                      rate[60s] series, and record that choice in the build summary.
   cpu_limit_ratio  = cpu_cores / CPU limit (cores)
   mem_limit_ratio  = container_memory_working_set_bytes / memory limit bytes
   net_rx_pkts, net_tx_pkts, net_drop_pkts = per-second packet rates (pod network namespace; drops = rx+tx dropped)
   Exclude POD/pause containers and sidecars. Missing samples stay NaN (pod_failure!), never 0.
3. Spans (canonical-v2-*/traces.parquet, OTel): service.name -> canonical name (frontend, redis-cart);
   parent join exactly as re2ob.load_spans (parent_service, parent_dur_s); err = status code ERROR.
   Drop spans of the load generator itself; keep the frontend server spans.
4. Build with features.build_* using the same compute code; check per-case window counts and that the
   ranking table holds only fault_active windows of eligible fault runs.
5. Edge table: same edges.parquet layout as RE2-OB (calls, err, p90 per window and caller->callee) for
   evaluation.edge_rank.
6. Sanity checks before any model is applied (allowed to look at): signal coverage per service, NaN share,
   baseline length per case, controls vs faults window counts. Do not look at scores or rankings here.
"""


def list_cases(root):
    raise NotImplementedError("linux-v1 adapter is implemented once formal pairs exist")


def load_metrics(case):
    raise NotImplementedError


def load_spans(case):
    raise NotImplementedError


def load_logs(case):
    raise NotImplementedError
