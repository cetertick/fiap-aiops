"""
AIOps agent -- control loop entrypoint.

The whole demo is this loop, run once every POLL_INTERVAL_SECONDS:

    for each watched app:
        observe   -> query Prometheus (error ratio, p95 latency, memory)
                     and the Kubernetes API (CrashLoopBackOff, restarts)
        detect    -> compare against the fixed thresholds in config.py
        remediate -> delete the bad pod / scale up / disable chaos
        audit     -> structured log line + Kubernetes Event + /actions entry

A separate thread runs a tiny Flask app exposing /metrics, /actions and
/health so the loop's own behaviour is observable like any other workload.
"""
import logging
import threading
import time

import config
import k8s_client
import metrics
import promclient
import remediation
import state
from logutil import log_event

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("aiops-agent")


def check_app(app: str, now: float):
    """Run one detection+remediation pass for a single app. Every step is
    wrapped so a failure here never stops the loop from checking the other
    apps or from running again in POLL_INTERVAL_SECONDS."""

    # --- 1. HighErrorRate -------------------------------------------------
    try:
        error_ratio = promclient.get_error_ratio(app)
        if error_ratio is not None and error_ratio > config.ERROR_RATE_THRESHOLD:
            handle_anomaly(
                app, "HighErrorRate", now,
                details={"error_ratio": round(error_ratio, 4), "threshold": config.ERROR_RATE_THRESHOLD},
                remediate=lambda: _remediate_pod_restart(app, "HighErrorRate", {"error_ratio": round(error_ratio, 4)}),
            )
    except Exception:
        log.exception("error-rate check failed for app=%s", app)

    # --- 2. HighLatencyP95 -------------------------------------------------
    try:
        p95 = promclient.get_p95_latency_seconds(app)
        if p95 is not None and p95 > config.LATENCY_P95_THRESHOLD_SECONDS:
            handle_anomaly(
                app, "HighLatencyP95", now,
                details={"p95_seconds": round(p95, 3), "threshold": config.LATENCY_P95_THRESHOLD_SECONDS},
                remediate=lambda: remediation.scale_up(app, "HighLatencyP95", {"p95_seconds": round(p95, 3)}),
            )
    except Exception:
        log.exception("latency check failed for app=%s", app)

    # --- 3. PodCrashLooping -------------------------------------------------
    try:
        pod_name, reason, restarts = k8s_client.find_crashlooping_pod(app)
        if pod_name:
            handle_anomaly(
                app, "PodCrashLooping", now,
                details={"pod": pod_name, "reason": reason, "restart_count": restarts},
                remediate=lambda: _remediate_pod_restart(
                    app, "PodCrashLooping", {"pod": pod_name, "reason": reason, "restart_count": restarts}, pod_name
                ),
            )
    except Exception:
        log.exception("crashloop check failed for app=%s", app)

    # --- 4. HighMemoryUsage -------------------------------------------------
    try:
        mem_ratios = promclient.get_memory_ratio_by_pod(app)
        for pod_name, ratio in mem_ratios.items():
            if ratio > config.MEMORY_RATIO_THRESHOLD:
                handle_anomaly(
                    app, "HighMemoryUsage", now,
                    details={"pod": pod_name, "memory_ratio": round(ratio, 4), "threshold": config.MEMORY_RATIO_THRESHOLD},
                    remediate=lambda pod_name=pod_name, ratio=ratio: _remediate_pod_restart(
                        app, "HighMemoryUsage", {"pod": pod_name, "memory_ratio": round(ratio, 4)}, pod_name
                    ),
                )
                break  # one remediation per app per loop iteration is enough
    except Exception:
        log.exception("memory check failed for app=%s", app)


def _remediate_pod_restart(app, anomaly_type, reason_details, pod_name=None):
    if pod_name is None:
        # HighErrorRate doesn't name a specific pod -- pick any pod for the
        # app so the restart+recreate cycle still clears a bad in-memory
        # state (e.g. a stuck feature flag/cache) on that instance.
        pods = k8s_client.list_pods_for_app(app)
        pod_name = pods[0].metadata.name if pods else None
    remediation.restart_offending_pod(app, anomaly_type, pod_name, reason_details)


def handle_anomaly(app: str, anomaly_type: str, now: float, details: dict, remediate):
    """Common anomaly handling: log, count, and -- unless in cooldown --
    remediate."""
    log_event("warning", anomaly_type, app, **details)
    metrics.anomalies_detected_total.labels(app=app, type=anomaly_type).inc()

    if state.is_in_cooldown(app, anomaly_type, now):
        log.info("skipping remediation for %s/%s: in cooldown", app, anomaly_type)
        return

    remediate()
    state.mark_remediated(app, anomaly_type, now)


def control_loop():
    log.info(
        "starting AIOps control loop: apps=%s interval=%ss cooldown=%ss",
        config.WATCHED_APPS, config.POLL_INTERVAL_SECONDS, config.COOLDOWN_SECONDS,
    )
    while True:
        metrics.agent_up.set(1)
        now = time.time()
        for app in config.WATCHED_APPS:
            try:
                check_app(app, now)
            except Exception:
                # Belt and suspenders -- check_app already catches per-check,
                # but nothing is allowed to kill the loop.
                log.exception("unexpected error checking app=%s", app)
        time.sleep(config.POLL_INTERVAL_SECONDS)


def build_http_app():
    from flask import Flask, jsonify, Response

    app = Flask("aiops-agent")

    @app.get("/metrics")
    def _metrics():
        return Response(metrics.render(), mimetype="text/plain; version=0.0.4")

    @app.get("/actions")
    def _actions():
        return jsonify(state.get_actions())

    @app.get("/health")
    def _health():
        return jsonify({"status": "ok"})

    return app


def main():
    k8s_client.init()

    http_app = build_http_app()
    http_thread = threading.Thread(
        target=lambda: http_app.run(host="0.0.0.0", port=config.METRICS_PORT, use_reloader=False),
        daemon=True,
        name="http-server",
    )
    http_thread.start()
    log.info("HTTP server listening on :%s (/metrics, /actions, /health)", config.METRICS_PORT)

    control_loop()


if __name__ == "__main__":
    main()
