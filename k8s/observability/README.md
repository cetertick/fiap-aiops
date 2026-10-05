# AIOps Lab — Observability Stack

Prometheus + Grafana + Alertmanager (via `kube-prometheus-stack`), Loki
(logs), Tempo (traces), and an OpenTelemetry Collector, all in the
`monitoring` namespace. Built for a 1h20 live class — everything here is
sized for a short-lived cluster, not production.

## File map

```
k8s/observability/
  namespace.yaml                        # `monitoring` namespace
  values/
    values-kube-prometheus-stack.yaml   # Prometheus+Grafana+Alertmanager+kube-state-metrics
    values-loki.yaml                    # Loki + Promtail (loki-stack chart)
    values-tempo.yaml                   # Tempo (single binary)
    values-otel-collector.yaml          # OTel Collector (deployment mode)
  alerting/
    contactpoints-configmap.yaml        # Grafana contact points: discord-alerts, postmortem-webhook
    policies-configmap.yaml             # Grafana notification policy: route ALL alerts to both
    rules-configmap.yaml                # 4 anomaly alert rules, folder "AIOps Lab Alerts"
  dashboards/
    <app>-dashboard.json                # Grafana dashboard model, one per demo app
    <app>-dashboard-configmap.yaml       # wraps the JSON for the Grafana sidecar
  README.md                             # this file

k8s/argocd/
  argocd-ingress.yaml                   # ALB Ingress for argocd-server (HTTP/--insecure)
  root-app-of-apps.yaml                 # root Application (app-of-apps)
  apps/*.yaml                           # one child Application per component
```

## Install order

### Path A — ArgoCD (preferred)

1. Install ArgoCD itself (not included in this repo — e.g.
   `kubectl create namespace argocd && kubectl apply -n argocd -f
   https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml`).
2. **Before syncing anything**, create the Discord webhook secret (see
   below) in `monitoring` — the namespace is auto-created by the
   kube-prometheus-stack Application's `CreateNamespace=true`, but you can
   also apply `k8s/observability/namespace.yaml` by hand first if you'd
   rather create the secret ahead of the namespace existing:
   ```
   kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
   kubectl create secret generic discord-webhook -n monitoring \
     --from-literal=url=https://discord.com/api/webhooks/XXXX/YYYY
   ```
3. Patch argocd-server to run insecure (HTTP) and apply the ALB Ingress, so
   you can reach the ArgoCD UI without extra TLS setup during class:
   ```
   kubectl -n argocd patch configmap argocd-cmd-params-cm --type merge \
     -p '{"data":{"server.insecure":"true"}}'
   kubectl -n argocd rollout restart deployment argocd-server
   kubectl apply -f k8s/argocd/argocd-ingress.yaml
   ```
4. Apply the root Application. ArgoCD takes it from here:
   ```
   kubectl apply -f k8s/argocd/root-app-of-apps.yaml
   ```
5. Once kube-prometheus-stack's Grafana pod is `Running`, load the dashboard
   and alerting ConfigMaps (these are plain ConfigMaps picked up by
   Grafana's sidecars — they are intentionally **not** wired into an ArgoCD
   Application, see "Judgment calls" below):
   ```
   kubectl apply -f k8s/observability/dashboards/orders-api-dashboard-configmap.yaml \
                  -f k8s/observability/dashboards/payments-api-dashboard-configmap.yaml \
                  -f k8s/observability/dashboards/inventory-api-dashboard-configmap.yaml \
                  -f k8s/observability/alerting/contactpoints-configmap.yaml \
                  -f k8s/observability/alerting/policies-configmap.yaml \
                  -f k8s/observability/alerting/rules-configmap.yaml
   ```

### Path B — manual Helm (fallback if ArgoCD isn't ready yet)

Run these in parallel background terminals while the instructor talks —
they don't depend on each other:

```
kubectl apply -f k8s/observability/namespace.yaml
kubectl create secret generic discord-webhook -n monitoring \
  --from-literal=url=https://discord.com/api/webhooks/XXXX/YYYY

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update

helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring -f k8s/observability/values/values-kube-prometheus-stack.yaml &

helm install loki grafana/loki-stack \
  -n monitoring -f k8s/observability/values/values-loki.yaml &

helm install tempo grafana/tempo \
  -n monitoring -f k8s/observability/values/values-tempo.yaml &

helm install otel-collector open-telemetry/opentelemetry-collector \
  -n monitoring -f k8s/observability/values/values-otel-collector.yaml &
wait

kubectl apply -f k8s/observability/dashboards/ -f k8s/observability/alerting/
```

Approximate install time (class can keep talking while these finish):

| Component            | ~Install time |
|-----------------------|---------------|
| kube-prometheus-stack | 3–5 min       |
| loki                  | 1–2 min       |
| tempo                 | 1–2 min       |
| otel-collector        | ~1 min        |

## Exact service DNS names / ports (contract reference)

| Component       | Service DNS                                              | Port(s)          |
|------------------|-----------------------------------------------------------|------------------|
| Prometheus       | `kube-prometheus-stack-prometheus.monitoring.svc.cluster.local` | 9090 |
| Alertmanager     | `kube-prometheus-stack-alertmanager.monitoring.svc.cluster.local` | 9093 |
| Grafana          | `kube-prometheus-stack-grafana.monitoring.svc.cluster.local` | 80 |
| Loki             | `loki.monitoring.svc.cluster.local`                        | 3100 (HTTP push/query) |
| Tempo            | `tempo.monitoring.svc.cluster.local`                       | 3200 (HTTP/query), 4317 (OTLP gRPC) |
| OTel Collector   | `otel-collector.monitoring.svc.cluster.local`               | 4317 (OTLP gRPC), 4318 (OTLP HTTP) |
| aiops-agent (aiops-lab) | `aiops-agent.aiops-lab.svc.cluster.local`            | 9100 |
| postmortem-service (aiops-lab) | `postmortem-service.aiops-lab.svc.cluster.local` | 8080, route `POST /webhook/grafana` |

Apps export OTLP traces to `otel-collector.monitoring.svc.cluster.local:4317`,
which forwards them on to `tempo.monitoring.svc.cluster.local:4317`.

## Discord webhook secret

Create this **before** deploying kube-prometheus-stack/Grafana, in whichever
namespace Grafana runs in (`monitoring`):

```
kubectl create secret generic discord-webhook -n monitoring \
  --from-literal=url=https://discord.com/api/webhooks/<id>/<token>
```

Grafana picks it up as the `DISCORD_WEBHOOK_URL` env var
(`grafana.envValueFrom` in `values-kube-prometheus-stack.yaml`), and the
`discord-alerts` contact point (`alerting/contactpoints-configmap.yaml`)
references it as `$__env{DISCORD_WEBHOOK_URL}`.

If your Grafana version does not expand `$__env{...}` inside alerting
provisioning files (this is documented for datasource provisioning and is
believed to work generally for provisioning files, but hasn't been verified
against every chart/Grafana version), the fallback is: edit
`alerting/contactpoints-configmap.yaml` and paste the real webhook URL
directly into the `url:` field before applying it — then treat that edited
file as containing a secret (don't commit it).

## Grafana access

- URL: via the kube-prometheus-stack Grafana Service
  (`kube-prometheus-stack-grafana.monitoring.svc.cluster.local:80`) — port-forward
  for the class:
  ```
  kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
  ```
  (No public Ingress for Grafana is provisioned here — only ArgoCD gets the
  ALB Ingress, per the task scope. Add one the same way as
  `argocd-ingress.yaml` if you want public Grafana access during class.)
- User: `admin`
- Password: the placeholder in `values-kube-prometheus-stack.yaml`
  (`grafana.adminPassword: "CHANGE_ME_aiops2024"`) **— change this**, or
  retrieve/rotate it via the Secret the chart creates:
  ```
  kubectl -n monitoring get secret kube-prometheus-stack-grafana \
    -o jsonpath='{.data.admin-password}' | base64 -d
  ```

## Alerting provisioning: which mechanism and why

**Chosen: ConfigMap + sidecar** (`grafana.sidecar.alerts`, label
`grafana_alert: "1"`), not the values-driven
`grafana.alerting."rules.yaml"` keys.

Why: the values-driven mechanism is real and works on recent `grafana/grafana`
chart versions, but its exact nested-key shape (whether it's
`grafana.alerting."contactpoints.yaml"` as a raw string vs. a native YAML
map, and which chart version introduced it) has moved around across
releases and is easy to get subtly wrong in a way that fails silently rather
than erroring loudly — not something to discover live, 10 minutes before a
class. The ConfigMap-sidecar mechanism is the same mechanism already used
for dashboards here (`grafana.sidecar.dashboards`) and has been stable for a
long time: label a ConfigMap, the sidecar copies its file into Grafana's
provisioning directory, Grafana's file-provisioning loader (a stable,
long-documented feature) takes it from there. It also keeps the 4 alert
rules and 2 contact points as plain, readable YAML files
(`alerting/*-configmap.yaml`) instead of deeply nested Helm values.

## Judgment calls / deviations (flag these to the class organizer)

- Alerting is provisioned via ConfigMap sidecar, not Helm values — see above.
- `grafana.additionalDataSources` Loki/Tempo entries set explicit `uid: loki`
  / `uid: tempo` so the dashboards here and Tempo's `tracesToLogsV2` linking
  can reference them deterministically.
- Grafana alert rules' PromQL for `HighMemoryUsage` keeps
  `container_memory_working_set_bytes` / `container_spec_memory_limit_bytes`
  grouped by their native `pod`/`container`/`namespace` labels rather than
  forcing a `by (app)` aggregation, since cAdvisor-sourced container metrics
  don't carry an `app` label directly — the dashboards instead match pods by
  name prefix (`pod=~"<app>.*"`), matching how the demo apps are expected to
  be named.
- The 3 demo apps' manifests live flat under `k8s/apps/` (confirmed on disk:
  `orders-api-deployment.yaml`, `orders-api-service.yaml`,
  `orders-api-podmonitor.yaml`, etc., all siblings, plus one shared
  `k8s/apps/namespace.yaml`). All three demo-app Applications correctly use
  `path: k8s/apps` per the contract, but each scopes itself with
  `directory.include: "<app>-*.yaml"` so the three Applications don't each
  try to own (and prune) the other two apps' resources in that shared
  directory. `namespace.yaml` is intentionally matched by none of the three
  includes — apply it once by hand (`kubectl apply -f k8s/apps/namespace.yaml`)
  or via a separate Application if you want ArgoCD to manage it.
- Dashboard and alerting ConfigMaps are deployed by `kubectl apply`, not by
  a dedicated ArgoCD Application (not in the task's explicit list of
  required Applications, and a directory-source Application over
  `k8s/observability/` would need exclude globs for the non-manifest
  `values/*.yaml` and `dashboards/*.json` files, which felt like
  unnecessary fragility for a 1h20 class).
- Helm chart versions in `k8s/argocd/apps/*-app.yaml` (kube-prometheus-stack
  62.7.0, loki-stack 2.10.2, tempo 1.10.1, opentelemetry-collector 0.97.0)
  are known-good pins as of this lab's authoring, not guaranteed to be the
  very latest — run `helm search repo <chart> --versions` beforehand and
  bump if you want newer.
- kube-prometheus-stack's control-plane component scraping (etcd,
  controller-manager, scheduler, kube-proxy) is disabled, since these
  usually aren't scrapable on managed Kubernetes (EKS/GKE/AKS) and would
  otherwise just generate noisy "target down" alerts during class.
- Argo CD Applications for the Helm releases use the multi-source
  (`sources:`) syntax so values live in this git repo's `values/*.yaml`
  files instead of being duplicated inline in the Application manifests.
