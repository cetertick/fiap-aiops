"""
Minimal Prometheus instant-query client.

Only what the control loop needs: run a PromQL instant query and get back
plain Python values. Every call is defensive -- a Prometheus hiccup for one
app must never take down the whole agent.
"""
import logging

import requests

import config

log = logging.getLogger("aiops-agent.prom")


def _instant_query(promql: str):
    """Run a PromQL instant query. Returns the raw `result` list from
    Prometheus (a list of {"metric": {...}, "value": [ts, "val"]} dicts),
    or None if the query failed / Prometheus is unreachable."""
    url = f"{config.PROMETHEUS_URL}/api/v1/query"
    try:
        resp = requests.get(
            url, params={"query": promql}, timeout=config.HTTP_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") != "success":
            log.warning("prometheus query not successful: %s -> %s", promql, payload)
            return None
        return payload["data"]["result"]
    except Exception:
        log.exception("prometheus query failed: %s", promql)
        return None


def _scalar(promql: str):
    """Run an instant query expected to return a single scalar/vector value.
    Returns a float, or None if there was no data or the query errored."""
    result = _instant_query(promql)
    if not result:
        return None
    try:
        return float(result[0]["value"][1])
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def get_error_ratio(app: str):
    """5xx ratio over the detection window for `app`. None if no data
    (e.g. no traffic at all -> nothing to divide, not an anomaly)."""
    promql = (
        f'sum(rate(http_requests_total{{app="{app}",status=~"5.."}}[{config.PROM_WINDOW}])) '
        f'/ sum(rate(http_requests_total{{app="{app}"}}[{config.PROM_WINDOW}]))'
    )
    return _scalar(promql)


def get_p95_latency_seconds(app: str):
    """p95 request latency over the detection window for `app`, in seconds."""
    promql = (
        f'histogram_quantile(0.95, sum by (le) '
        f'(rate(http_request_duration_seconds_bucket{{app="{app}"}}[{config.PROM_WINDOW}])))'
    )
    return _scalar(promql)


def get_memory_ratio_by_pod(app: str):
    """Container memory working-set / limit ratio, per pod, for `app`.

    Returns a dict {pod_name: ratio}. The cAdvisor metrics
    (container_memory_working_set_bytes / container_spec_memory_limit_bytes)
    don't carry an `app` label, so pods are matched by name prefix -- the
    Deployment for `app` produces pods named "<app>-<hash>-<hash>".
    """
    promql = (
        f'container_memory_working_set_bytes{{namespace="{config.NAMESPACE}",'
        f'pod=~"^{app}-.*",container!="",container!="POD"}} '
        f'/ container_spec_memory_limit_bytes{{namespace="{config.NAMESPACE}",'
        f'pod=~"^{app}-.*",container!="",container!="POD"}}'
    )
    result = _instant_query(promql)
    if not result:
        return {}
    ratios = {}
    for series in result:
        pod = series.get("metric", {}).get("pod")
        if not pod:
            continue
        try:
            ratios[pod] = float(series["value"][1])
        except (KeyError, IndexError, ValueError, TypeError):
            continue
    return ratios
