"""Prometheus metrics exposed by the agent itself (its own /metrics
endpoint, scraped via the PodMonitor in k8s/podmonitor.yaml)."""
from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

registry = CollectorRegistry()

anomalies_detected_total = Counter(
    "aiops_anomalies_detected_total",
    "Number of anomalies detected by the AIOps agent",
    ["app", "type"],
    registry=registry,
)

actions_taken_total = Counter(
    "aiops_actions_taken_total",
    "Number of remediation actions taken by the AIOps agent",
    ["app", "action"],
    registry=registry,
)

agent_up = Gauge(
    "aiops_agent_up",
    "Heartbeat: 1 while the AIOps agent control loop is running",
    registry=registry,
)
agent_up.set(1)


def render() -> bytes:
    return generate_latest(registry)
