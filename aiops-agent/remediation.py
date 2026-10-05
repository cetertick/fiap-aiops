"""
Remediation actions the agent can take, and the chaos "circuit breaker"
call shared by several of them.
"""
import logging

import requests

import config
import k8s_client
import metrics
import state
from logutil import log_event

log = logging.getLogger("aiops-agent.remediation")


def disable_chaos(app: str) -> bool:
    """POST /chaos/disable on the app's own Service -- the 'circuit
    breaker' step that turns off whatever injected chaos/bad feature flag
    is likely causing the anomaly."""
    port = config.APP_PORTS.get(app)
    url = f"http://{app}.{config.NAMESPACE}.svc.cluster.local:{port}/chaos/disable"
    try:
        resp = requests.post(url, timeout=config.HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
        log.info("disabled chaos on %s", app)
        metrics.actions_taken_total.labels(app=app, action="chaos_disable").inc()
        return True
    except Exception as exc:
        log.warning("failed to disable chaos on %s: %s", app, exc)
        log_event("warning", "RemediationCallFailed", app, action="chaos_disable", error=str(exc))
        return False


def restart_offending_pod(app: str, anomaly_type: str, pod_name: str, reason_details: dict):
    """Delete the offending pod (so the Deployment recreates it fresh) and
    disable chaos on the app. Used for HighErrorRate, PodCrashLooping and
    HighMemoryUsage."""
    deleted = False
    if pod_name:
        deleted = k8s_client.delete_pod(pod_name)
        if deleted:
            metrics.actions_taken_total.labels(app=app, action="pod_restart").inc()

    chaos_ok = disable_chaos(app)

    message = (
        f"Detected {anomaly_type} on {app} ({reason_details}). "
        f"Action: restarted pod {pod_name or '<none>'} (success={deleted}), "
        f"disabled chaos (success={chaos_ok})."
    )
    k8s_client.create_event(
        reason="AIOpsAutoRemediation",
        message=message,
        app=app,
        involved_object_name=pod_name or app,
        involved_object_kind="Pod" if pod_name else "Deployment",
        event_type="Normal",
    )
    state.record_action(
        app=app,
        anomaly_type=anomaly_type,
        action="pod_restart+chaos_disable",
        details={"pod": pod_name, "pod_deleted": deleted, "chaos_disabled": chaos_ok, **reason_details},
    )
    log_event(
        "info", "RemediationTaken", app,
        anomaly_type=anomaly_type, action="pod_restart+chaos_disable",
        pod=pod_name, pod_deleted=deleted, chaos_disabled=chaos_ok,
    )


def scale_up(app: str, anomaly_type: str, reason_details: dict):
    """Scale the Deployment up by 1 (capped at MAX_REPLICAS) and disable
    chaos as a secondary safety action. Used for HighLatencyP95."""
    current = k8s_client.get_deployment_replicas(app)
    scaled = False
    new_replicas = current
    if current is not None:
        new_replicas = min(current + 1, config.MAX_REPLICAS)
        if new_replicas != current:
            scaled = k8s_client.scale_deployment(app, new_replicas)
            if scaled:
                metrics.actions_taken_total.labels(app=app, action="scale_up").inc()
        else:
            log.info("%s already at MAX_REPLICAS=%s, not scaling further", app, config.MAX_REPLICAS)

    chaos_ok = disable_chaos(app)

    message = (
        f"Detected {anomaly_type} on {app} ({reason_details}). "
        f"Action: scaled replicas {current} -> {new_replicas} (success={scaled}), "
        f"disabled chaos (success={chaos_ok})."
    )
    k8s_client.create_event(
        reason="AIOpsAutoRemediation",
        message=message,
        app=app,
        involved_object_name=app,
        involved_object_kind="Deployment",
        event_type="Normal",
    )
    state.record_action(
        app=app,
        anomaly_type=anomaly_type,
        action="scale_up+chaos_disable",
        details={
            "replicas_before": current, "replicas_after": new_replicas,
            "scaled": scaled, "chaos_disabled": chaos_ok, **reason_details,
        },
    )
    log_event(
        "info", "RemediationTaken", app,
        anomaly_type=anomaly_type, action="scale_up+chaos_disable",
        replicas_before=current, replicas_after=new_replicas, chaos_disabled=chaos_ok,
    )
