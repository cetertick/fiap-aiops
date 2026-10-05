"""
Thin wrapper around the Kubernetes Python client.

All the Kubernetes API calls the control loop needs live here: listing pods
for an app, detecting CrashLoopBackOff, deleting a pod, scaling a
Deployment, and writing an audit Event. Every public function catches its
own exceptions and logs instead of raising, so one bad call never stops the
loop from checking the next app.
"""
import datetime
import logging
import time

from kubernetes import client, config as k8s_config
from kubernetes.client.rest import ApiException

import config

log = logging.getLogger("aiops-agent.k8s")

_core_v1 = None
_apps_v1 = None


def init():
    """Load in-cluster config and build the API clients. Call once at
    startup. Falls back to kubeconfig for local/dev runs outside a cluster."""
    global _core_v1, _apps_v1
    try:
        k8s_config.load_incluster_config()
        log.info("loaded in-cluster kubeconfig")
    except Exception:
        k8s_config.load_kube_config()
        log.info("loaded local kubeconfig (not running in-cluster)")
    _core_v1 = client.CoreV1Api()
    _apps_v1 = client.AppsV1Api()


def list_pods_for_app(app: str):
    """Return the list of V1Pod objects for `app` in the watched namespace,
    or [] on error."""
    try:
        pods = _core_v1.list_namespaced_pod(
            namespace=config.NAMESPACE, label_selector=f"app={app}"
        )
        return pods.items
    except ApiException:
        log.exception("failed to list pods for app=%s", app)
        return []


def find_crashlooping_pod(app: str):
    """Inspect this app's pods for CrashLoopBackOff or a fast-rising
    restart count. Returns (pod_name, reason, restart_count) for the first
    offending pod found, or (None, None, 0) if none are crash-looping."""
    for pod in list_pods_for_app(app):
        statuses = pod.status.container_statuses or []
        for cs in statuses:
            waiting = cs.state.waiting if cs.state else None
            restart_count = cs.restart_count or 0
            if waiting and waiting.reason == "CrashLoopBackOff":
                return pod.metadata.name, "CrashLoopBackOff", restart_count
            # Rapidly increasing restarts without (yet) a CrashLoopBackOff
            # waiting reason is still a strong signal something is wrong.
            if restart_count >= 5:
                return pod.metadata.name, "HighRestartCount", restart_count
    return None, None, 0


def delete_pod(pod_name: str) -> bool:
    """Delete a pod so its ReplicaSet/Deployment recreates it fresh.
    Returns True on success."""
    try:
        _core_v1.delete_namespaced_pod(name=pod_name, namespace=config.NAMESPACE)
        log.info("deleted pod %s/%s for remediation", config.NAMESPACE, pod_name)
        return True
    except ApiException:
        log.exception("failed to delete pod %s", pod_name)
        return False


def get_deployment_replicas(app: str):
    """Return the current spec.replicas for the Deployment named `app`, or
    None if it couldn't be read."""
    try:
        dep = _apps_v1.read_namespaced_deployment(name=app, namespace=config.NAMESPACE)
        return dep.spec.replicas
    except ApiException:
        log.exception("failed to read deployment %s", app)
        return None


def scale_deployment(app: str, new_replicas: int) -> bool:
    """Patch the Deployment's spec.replicas. Returns True on success."""
    try:
        patch_body = {"spec": {"replicas": new_replicas}}
        _apps_v1.patch_namespaced_deployment_scale(
            name=app, namespace=config.NAMESPACE, body=patch_body
        )
        log.info("scaled deployment %s to %s replicas", app, new_replicas)
        return True
    except ApiException:
        log.exception("failed to scale deployment %s", app)
        return False


def create_event(
    reason: str,
    message: str,
    app: str,
    involved_object_name: str,
    involved_object_kind: str = "Pod",
    event_type: str = "Normal",
) -> bool:
    """Write a Kubernetes Event in the watched namespace for audit
    visibility (`kubectl get events -n aiops-lab --watch`)."""
    now = time.time()
    event_time = datetime.datetime.fromtimestamp(now, tz=datetime.timezone.utc)
    name = f"aiops-agent-{involved_object_name}-{int(now * 1000)}"
    body = client.V1Event(
        metadata=client.V1ObjectMeta(name=name, namespace=config.NAMESPACE),
        involved_object=client.V1ObjectReference(
            kind=involved_object_kind,
            name=involved_object_name,
            namespace=config.NAMESPACE,
        ),
        reason=reason,
        message=message[:1024],  # Events truncate long messages anyway
        type=event_type,
        source=client.V1EventSource(component="aiops-agent"),
        first_timestamp=event_time,
        last_timestamp=event_time,
        count=1,
    )
    try:
        _core_v1.create_namespaced_event(namespace=config.NAMESPACE, body=body)
        return True
    except ApiException:
        log.exception("failed to create audit event for %s/%s", app, involved_object_name)
        return False
