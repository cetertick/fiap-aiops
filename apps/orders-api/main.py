"""
orders-api - FIAP AIOps teaching lab demo service.

Simple FastAPI app with:
  - business endpoints: GET /orders, POST /orders
  - /health, /metrics (Prometheus), /chaos/* (chaos injection)
  - structured JSON logs to stdout
  - basic OpenTelemetry tracing (OTLP/gRPC)

Kept intentionally small and readable for a live class.
"""

import json
import os
import random
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

APP_NAME = "orders-api"

# ---------------------------------------------------------------------------
# Logging (structured JSON lines to stdout, scraped by Promtail/Loki)
# ---------------------------------------------------------------------------

def log_json(level: str, msg: str, **fields):
    record = {
        "level": level,
        "msg": msg,
        "app": APP_NAME,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    record.update(fields)
    print(json.dumps(record), flush=True)


# ---------------------------------------------------------------------------
# OpenTelemetry tracing (minimal demo setup)
# ---------------------------------------------------------------------------

OTEL_EXPORTER_OTLP_ENDPOINT = os.environ.get(
    "OTEL_EXPORTER_OTLP_ENDPOINT", "otel-collector.monitoring.svc.cluster.local:4317"
)

_provider = TracerProvider(resource=Resource.create({"service.name": APP_NAME}))
_exporter = OTLPSpanExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT, insecure=True)
_provider.add_span_processor(BatchSpanProcessor(_exporter))
trace.set_tracer_provider(_provider)
tracer = trace.get_tracer(APP_NAME)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status", "app"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path", "app"],
)

# ---------------------------------------------------------------------------
# Chaos state
# ---------------------------------------------------------------------------
# mode: none | latency | crash | memory_leak | http_errors

CHAOS_DEFAULT_INTENSITY = {
    "latency": 2000,       # ms
    "http_errors": 50,     # percent
    "crash": 5,            # requests
    "memory_leak": 0,      # unused
    "none": 0,
}

chaos_state = {
    "enabled": os.environ.get("CHAOS_ENABLED", "false").lower() == "true",
    "mode": os.environ.get("CHAOS_MODE", "none"),
    "intensity": float(os.environ.get("CHAOS_INTENSITY", "0")),
}

_chaos_lock = threading.Lock()
_crash_request_count = 0
_memory_leak_buffer = []  # list of bytearrays, retained to grow RSS


def _memory_leak_loop():
    """Background thread: while chaos is memory_leak + enabled, grow memory ~1MB/s."""
    while True:
        time.sleep(1)
        with _chaos_lock:
            active = chaos_state["enabled"] and chaos_state["mode"] == "memory_leak"
        if active:
            _memory_leak_buffer.append(bytearray(1024 * 1024))  # ~1MB
            log_json(
                "error",
                "chaos: memory leak tick",
                method="",
                path="",
                status=0,
                duration_ms=0,
                total_leaked_mb=len(_memory_leak_buffer),
            )


threading.Thread(target=_memory_leak_loop, daemon=True).start()


def apply_chaos(method: str, path: str):
    """Applies chaos effects for a business endpoint. May sleep, raise, or exit the process.

    Returns a JSONResponse to short-circuit with an error, or None to continue normally.
    """
    global _crash_request_count

    with _chaos_lock:
        enabled = chaos_state["enabled"]
        mode = chaos_state["mode"]
        intensity = chaos_state["intensity"]

    if not enabled or mode == "none":
        return None

    if mode == "latency":
        delay_ms = intensity if intensity else CHAOS_DEFAULT_INTENSITY["latency"]
        log_json("error", "chaos: injecting latency", method=method, path=path,
                  status=0, duration_ms=delay_ms)
        time.sleep(delay_ms / 1000.0)
        return None

    if mode == "http_errors":
        pct = intensity if intensity else CHAOS_DEFAULT_INTENSITY["http_errors"]
        if random.random() * 100 < pct:
            log_json("error", "chaos: injected 500", method=method, path=path,
                      status=500, duration_ms=0)
            return JSONResponse(status_code=500, content={"error": "chaos: injected failure"})
        return None

    if mode == "crash":
        limit = int(intensity) if intensity else CHAOS_DEFAULT_INTENSITY["crash"]
        with _chaos_lock:
            _crash_request_count += 1
            count = _crash_request_count
        log_json("error", "chaos: crash mode request counted", method=method, path=path,
                  status=0, duration_ms=0, request_count=count, limit=limit)
        if count >= limit:
            log_json("error", "chaos: crashing on purpose", method=method, path=path,
                      status=0, duration_ms=0)
            sys.stdout.flush()
            os._exit(1)
        return None

    # memory_leak mode doesn't affect individual request handling; the background
    # thread does the leaking. Nothing to do here.
    return None


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="orders-api")


@app.middleware("http")
async def metrics_and_logging_middleware(request: Request, call_next):
    start = time.time()
    method = request.method
    path = request.url.path
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception:
        status = 500
        raise
    finally:
        duration = time.time() - start
        REQUEST_COUNT.labels(method=method, path=path, status=str(status), app=APP_NAME).inc()
        REQUEST_LATENCY.labels(method=method, path=path, app=APP_NAME).observe(duration)
        log_json(
            "info" if status < 500 else "error",
            "request handled",
            method=method,
            path=path,
            status=status,
            duration_ms=round(duration * 1000, 2),
        )
    return response


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/chaos/status")
async def chaos_status():
    with _chaos_lock:
        return dict(chaos_state)


@app.post("/chaos/enable")
async def chaos_enable(request: Request):
    global _crash_request_count
    body = await request.json()
    mode = body.get("mode", "none")
    intensity = body.get("intensity")
    if intensity is None:
        intensity = CHAOS_DEFAULT_INTENSITY.get(mode, 0)
    with _chaos_lock:
        chaos_state["enabled"] = True
        chaos_state["mode"] = mode
        chaos_state["intensity"] = float(intensity)
        _crash_request_count = 0
        result = dict(chaos_state)
    log_json("info", "chaos: enabled", method="POST", path="/chaos/enable", status=200,
              duration_ms=0, mode=mode, intensity=intensity)
    return result


@app.post("/chaos/disable")
async def chaos_disable():
    global _crash_request_count
    with _chaos_lock:
        chaos_state["enabled"] = False
        chaos_state["mode"] = "none"
        chaos_state["intensity"] = 0
        _crash_request_count = 0
        _memory_leak_buffer.clear()
        result = dict(chaos_state)
    log_json("info", "chaos: disabled", method="POST", path="/chaos/disable", status=200,
              duration_ms=0)
    return result


# ---------------------------------------------------------------------------
# Business endpoints
# ---------------------------------------------------------------------------

FAKE_ORDERS = [
    {"id": "ord-1001", "item": "widget", "quantity": 2, "status": "confirmed"},
    {"id": "ord-1002", "item": "gadget", "quantity": 1, "status": "pending"},
    {"id": "ord-1003", "item": "gizmo", "quantity": 5, "status": "shipped"},
]


@app.get("/orders")
async def get_orders(request: Request):
    with tracer.start_as_current_span("orders-api.handle_orders"):
        chaos_response = apply_chaos("GET", "/orders")
        if chaos_response is not None:
            return chaos_response
        return {"orders": FAKE_ORDERS}


@app.post("/orders")
async def create_order(request: Request):
    with tracer.start_as_current_span("orders-api.handle_orders"):
        chaos_response = apply_chaos("POST", "/orders")
        if chaos_response is not None:
            return chaos_response
        body = await request.json()
        new_order = dict(body)
        new_order["id"] = f"ord-{uuid.uuid4().hex[:8]}"
        new_order["status"] = "created"
        return new_order


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
