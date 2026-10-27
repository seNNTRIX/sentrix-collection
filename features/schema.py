"""Constants shared by every data source. See docs/RE2OB-DECISIONS.md."""

import os

FEATURE_VERSION = "v0"

# Default 30 s (feature-schema.yaml). SENTRIX_WINDOW_SECONDS overrides it for the
# R4 window-length comparison only; the build summary records the value used.
WINDOW_SECONDS = int(os.environ.get("SENTRIX_WINDOW_SECONDS", "30"))
STRIDE_SECONDS = 10
RESAMPLE_SECONDS = 5

# Trace quantiles are only computed with enough spans (feature-schema.yaml).
MIN_SPANS = {"p50": 5, "p90": 20, "p99": 100}

# Canonical Online Boutique services = ranking candidates for both datasets.
CANDIDATES = (
    "adservice", "cartservice", "checkoutservice", "currencyservice", "emailservice",
    "frontend", "paymentservice", "productcatalogservice", "recommendationservice",
    "redis-cart", "shippingservice",
)

# Metric signals every adapter must provide in long format (service, t, signal, value).
METRIC_SIGNALS = (
    "cpu_cores",          # CPU usage in cores
    "cpu_limit_ratio",    # cpu_cores / CPU limit in cores (NaN when no limit)
    "mem_limit_ratio",    # working set / memory limit
    "net_rx_pkts",        # received packets per second
    "net_tx_pkts",        # transmitted packets per second
    "net_drop_pkts",      # rx + tx dropped packets per second
)

# Column prefixes. Only columns starting with "f_" are model inputs.
FEATURE_PREFIX = "f_"
META_PREFIX = "meta_"
TARGET_COLUMN = "target"

# Feature bundles (selected by prefix after "f_"); R4 decides which to keep.
BUNDLES = {
    "core_metric": "f_cm_",
    "core_trace": "f_ct_",
    "optional": "f_opt_",
    "exp_log": "f_log_",
    "exp_neighbor": "f_nbr_",
}

# Strings that must never appear in a model-input column name
# (campaigns/linux-v1/feature-schema.yaml forbidden_features).
FORBIDDEN_NAME_PARTS = (
    "service_name", "case", "pair", "run_id", "repetition", "fold", "timestamp",
    "onset", "elapsed", "phase", "pod", "container_id", "chaos", "fault_type", "target",
) + CANDIDATES
