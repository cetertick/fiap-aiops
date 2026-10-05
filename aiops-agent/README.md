# AIOps Agent

A small Kubernetes-native controller that closes the loop:

```
observe (Prometheus + K8s API) -> detect anomaly -> remediate automatically -> audit
```

It watches the three demo apps in the `aiops-lab` namespace (`orders-api`,
`payments-api`, `inventory-api`), and when it sees one of the four anomaly
types below, it takes an automatic remediation action and records *why* —
as a structured log line, a Prometheus counter, a Kubernetes `Event`, and an
entry in its own in-memory action log (`/actions`).

## Detection thresholds

These match exactly the thresholds encoded in the Grafana/Prometheus alert
rules, so both systems "see" the same anomaly during the demo.

| Anomaly          | Condition                                                              | Window |
|------------------|-------------------------------------------------------------------------|--------|
| `HighErrorRate`  | 5xx responses / total responses > **20%**                              | 2m     |
| `HighLatencyP95` | p95 request latency > **1.5s**                                         | 2m     |
| `PodCrashLooping`| a pod's container is `waiting.reason == CrashLoopBackOff`, or has a fast-rising restart count (>= 5) | instant |
| `HighMemoryUsage`| container `memory working set / limit` > **85%** (memory-leak proxy)   | instant |

PromQL used (per app, `<app>` substituted):

```promql
# HighErrorRate
sum(rate(http_requests_total{app="<app>",status=~"5.."}[2m]))
  / sum(rate(http_requests_total{app="<app>"}[2m]))

# HighLatencyP95
histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{app="<app>"}[2m])))

# HighMemoryUsage (per pod, matched by name prefix "<app>-")
container_memory_working_set_bytes{namespace="aiops-lab",pod=~"^<app>-.*",container!="",container!="POD"}
  / container_spec_memory_limit_bytes{namespace="aiops-lab",pod=~"^<app>-.*",container!="",container!="POD"}
```

`PodCrashLooping` is detected directly via the Kubernetes API (listing pods
with label `app=<app>` in `aiops-lab` and inspecting
`status.container_statuses[].state.waiting.reason`), not via PromQL.

## Remediation actions

| Anomaly           | Action(s) taken                                                                 |
|-------------------|------------------------------------------------------------------------------------|
| `HighErrorRate`   | Delete the pod (Deployment recreates it fresh) **+** call `POST /chaos/disable` on the app |
| `PodCrashLooping` | Delete the crash-looping pod **+** call `POST /chaos/disable` on the app          |
| `HighMemoryUsage` | Delete the offending pod **+** call `POST /chaos/disable` on the app              |
| `HighLatencyP95`  | Scale the Deployment `+1` replica (capped at `MAX_REPLICAS`, default 5) **+** call `POST /chaos/disable` on the app |

Every remediation:
1. increments `aiops_actions_taken_total{app,action}` (`pod_restart`, `scale_up`, `chaos_disable`),
2. writes a Kubernetes `Event` (reason `AIOpsAutoRemediation`) in `aiops-lab`,
3. appends an entry to the in-memory ring buffer served at `GET /actions`.

## Cooldown

The control loop runs every `POLL_INTERVAL_SECONDS` (default **15s**), but a
remediation like a pod restart or a scale-up takes real time to take
effect — a freshly-recreated pod is still warming up, metrics still reflect
the last couple of minutes via the `rate(...[2m])` window, etc. Without a
cooldown the agent would see the *same* anomaly again on the very next tick
and re-remediate every 15 seconds, thrashing the app (e.g. deleting a pod
that is still starting up).

`COOLDOWN_SECONDS` (default **60s**) tracks, per `(app, anomaly_type)` pair,
the timestamp of the last remediation. While inside the cooldown window the
agent still *detects and logs* the anomaly (so you keep seeing it in
`/actions`' sibling, the structured logs, and the anomaly counter), but
skips taking another action until the cooldown has elapsed.

## Watching it live during class

```bash
# Follow the control loop's structured JSON logs
kubectl logs -f deploy/aiops-agent -n aiops-lab

# Watch Kubernetes Events for every remediation as it happens
kubectl get events -n aiops-lab --watch

# See the agent's own action history (what it did and why)
kubectl port-forward svc/aiops-agent -n aiops-lab 9100:9100 &
curl -s localhost:9100/actions | jq

# Prometheus metrics the agent exposes about itself
curl -s localhost:9100/metrics
```

## Configuration (env vars)

| Variable                        | Default                                                              |
|----------------------------------|-----------------------------------------------------------------------|
| `NAMESPACE`                      | `aiops-lab`                                                           |
| `POLL_INTERVAL_SECONDS`          | `15`                                                                   |
| `COOLDOWN_SECONDS`               | `60`                                                                   |
| `MAX_REPLICAS`                   | `5`                                                                    |
| `WATCHED_APPS`                   | `orders-api,payments-api,inventory-api`                               |
| `APP_PORTS`                      | `orders-api=8000,payments-api=8001,inventory-api=8002`                |
| `PROMETHEUS_URL`                 | `http://kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090` |
| `LOKI_URL`                       | `http://loki.monitoring.svc.cluster.local:3100`                       |
| `ERROR_RATE_THRESHOLD`           | `0.20`                                                                 |
| `LATENCY_P95_THRESHOLD_SECONDS`  | `1.5`                                                                  |
| `MEMORY_RATIO_THRESHOLD`         | `0.85`                                                                 |
| `PROM_WINDOW`                    | `2m`                                                                   |
| `METRICS_PORT`                   | `9100`                                                                 |

## Notes / design choices

- This is a **singleton controller** (1 replica). Its cooldown and
  action-history state live in process memory, so it must not be scaled
  horizontally — scaling it would let multiple replicas remediate the same
  anomaly concurrently and lose the cooldown guarantee.
- The Kubernetes `Role`/`RoleBinding` are namespaced to `aiops-lab` only
  (least privilege) — no `ClusterRole` is used.
- `container_memory_working_set_bytes` / `container_spec_memory_limit_bytes`
  don't carry an `app` label (they come from cAdvisor via kubelet, not the
  app itself), so pods are matched to an app by name prefix
  (`pod=~"^<app>-.*"`), which works because each app's Deployment is named
  after the app.
- All Prometheus/Loki/Kubernetes calls are wrapped in `try/except` and
  logged — a single failed query never stops the loop from checking the
  other two apps or running again on the next tick.
