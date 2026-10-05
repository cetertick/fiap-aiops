"""
Configuration for the AIOps agent, all overridable via environment variables.

Keeping every tunable in one place makes it obvious what a student can change
without touching the control-loop logic in main.py.
"""
import os


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- Core loop ---------------------------------------------------------
NAMESPACE = os.environ.get("NAMESPACE", "aiops-lab")
POLL_INTERVAL_SECONDS = _env_int("POLL_INTERVAL_SECONDS", 15)
COOLDOWN_SECONDS = _env_int("COOLDOWN_SECONDS", 60)
MAX_REPLICAS = _env_int("MAX_REPLICAS", 5)

# --- Watched apps & their Service ports ---------------------------------
# Default matches the fixed contract: orders-api:8000, payments-api:8001,
# inventory-api:8002. Both lists must stay in the same order so apps line up
# with their ports when customised via env vars.
WATCHED_APPS = [
    a.strip() for a in os.environ.get(
        "WATCHED_APPS", "orders-api,payments-api,inventory-api"
    ).split(",") if a.strip()
]

_DEFAULT_PORTS = "orders-api=8000,payments-api=8001,inventory-api=8002"
_APP_PORTS_RAW = os.environ.get("APP_PORTS", _DEFAULT_PORTS)


def _parse_app_ports(raw: str) -> dict:
    ports = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, port = pair.split("=", 1)
        try:
            ports[name.strip()] = int(port.strip())
        except ValueError:
            continue
    return ports


APP_PORTS = _parse_app_ports(_APP_PORTS_RAW)
# Fallback so an app without an explicit port mapping still gets *something*
# sensible instead of crashing the loop.
for _i, _app in enumerate(WATCHED_APPS):
    APP_PORTS.setdefault(_app, 8000 + _i)

# --- Backends -------------------------------------------------------------
PROMETHEUS_URL = os.environ.get(
    "PROMETHEUS_URL",
    "http://kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090",
)
LOKI_URL = os.environ.get(
    "LOKI_URL", "http://loki.monitoring.svc.cluster.local:3100"
)

# --- Thresholds (must match the Grafana alert rules exactly) --------------
ERROR_RATE_THRESHOLD = _env_float("ERROR_RATE_THRESHOLD", 0.20)  # 20%
LATENCY_P95_THRESHOLD_SECONDS = _env_float("LATENCY_P95_THRESHOLD_SECONDS", 1.5)
MEMORY_RATIO_THRESHOLD = _env_float("MEMORY_RATIO_THRESHOLD", 0.85)  # 85%
PROM_WINDOW = os.environ.get("PROM_WINDOW", "2m")

# --- HTTP server ------------------------------------------------------
METRICS_PORT = _env_int("METRICS_PORT", 9100)

# --- Misc ---------------------------------------------------------------
HTTP_TIMEOUT_SECONDS = _env_float("HTTP_TIMEOUT_SECONDS", 5.0)
ACTIONS_RING_BUFFER_SIZE = _env_int("ACTIONS_RING_BUFFER_SIZE", 100)
