/**
 * payments-api - FIAP AIOps teaching lab demo service.
 *
 * Node.js 20 + Express. Business endpoints: POST /payments, GET /payments/:id.
 * Also exposes /health, /metrics (Prometheus), /chaos/* (chaos injection),
 * structured JSON logs to stdout, and basic OpenTelemetry tracing (OTLP/gRPC).
 *
 * Kept intentionally small and readable for a live class.
 */

'use strict';

const express = require('express');
const client = require('prom-client');

const { trace } = require('@opentelemetry/api');
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const { BatchSpanProcessor } = require('@opentelemetry/sdk-trace-base');
const { Resource } = require('@opentelemetry/resources');
const { SemanticResourceAttributes } = require('@opentelemetry/semantic-conventions');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-grpc');

const APP_NAME = 'payments-api';
const PORT = 8001;

// ---------------------------------------------------------------------------
// Logging (structured JSON lines to stdout, scraped by Promtail/Loki)
// ---------------------------------------------------------------------------

function logJson(level, msg, fields = {}) {
  const record = {
    level,
    msg,
    app: APP_NAME,
    ts: new Date().toISOString(),
    ...fields,
  };
  console.log(JSON.stringify(record));
}

// ---------------------------------------------------------------------------
// OpenTelemetry tracing (minimal demo setup)
// ---------------------------------------------------------------------------

const OTEL_EXPORTER_OTLP_ENDPOINT =
  process.env.OTEL_EXPORTER_OTLP_ENDPOINT || 'otel-collector.monitoring.svc.cluster.local:4317';

const traceExporter = new OTLPTraceExporter({
  url: OTEL_EXPORTER_OTLP_ENDPOINT,
});

const tracerProvider = new NodeTracerProvider({
  resource: new Resource({ [SemanticResourceAttributes.SERVICE_NAME]: APP_NAME }),
});
tracerProvider.addSpanProcessor(new BatchSpanProcessor(traceExporter));
tracerProvider.register();

const tracer = trace.getTracer(APP_NAME);

// ---------------------------------------------------------------------------
// Prometheus metrics
// ---------------------------------------------------------------------------

const register = client.register;

const httpRequestsTotal = new client.Counter({
  name: 'http_requests_total',
  help: 'Total HTTP requests',
  labelNames: ['method', 'path', 'status', 'app'],
});

const httpRequestDuration = new client.Histogram({
  name: 'http_request_duration_seconds',
  help: 'HTTP request latency in seconds',
  labelNames: ['method', 'path', 'app'],
});

// ---------------------------------------------------------------------------
// Chaos state
// ---------------------------------------------------------------------------
// mode: none | latency | crash | memory_leak | http_errors

const CHAOS_DEFAULT_INTENSITY = {
  latency: 2000, // ms
  http_errors: 50, // percent
  crash: 5, // requests
  memory_leak: 0, // unused
  none: 0,
};

const chaosState = {
  enabled: (process.env.CHAOS_ENABLED || 'false').toLowerCase() === 'true',
  mode: process.env.CHAOS_MODE || 'none',
  intensity: Number(process.env.CHAOS_INTENSITY || '0'),
};

let crashRequestCount = 0;
const memoryLeakBuffer = []; // array of Buffers, retained to grow RSS

setInterval(() => {
  if (chaosState.enabled && chaosState.mode === 'memory_leak') {
    memoryLeakBuffer.push(Buffer.alloc(1024 * 1024)); // ~1MB
    logJson('error', 'chaos: memory leak tick', {
      method: '',
      path: '',
      status: 0,
      duration_ms: 0,
      total_leaked_mb: memoryLeakBuffer.length,
    });
  }
}, 1000);

/**
 * Applies chaos effects for a business endpoint.
 * Returns a promise. If it resolves to an object with `shortCircuit: true`,
 * the caller should send that status/body and stop. Otherwise continue normally.
 */
async function applyChaos(method, path) {
  const { enabled, mode, intensity } = chaosState;

  if (!enabled || mode === 'none') {
    return { shortCircuit: false };
  }

  if (mode === 'latency') {
    const delayMs = intensity || CHAOS_DEFAULT_INTENSITY.latency;
    logJson('error', 'chaos: injecting latency', {
      method,
      path,
      status: 0,
      duration_ms: delayMs,
    });
    await new Promise((resolve) => setTimeout(resolve, delayMs));
    return { shortCircuit: false };
  }

  if (mode === 'http_errors') {
    const pct = intensity || CHAOS_DEFAULT_INTENSITY.http_errors;
    if (Math.random() * 100 < pct) {
      logJson('error', 'chaos: injected 500', { method, path, status: 500, duration_ms: 0 });
      return { shortCircuit: true, status: 500, body: { error: 'chaos: injected failure' } };
    }
    return { shortCircuit: false };
  }

  if (mode === 'crash') {
    const limit = intensity || CHAOS_DEFAULT_INTENSITY.crash;
    crashRequestCount += 1;
    logJson('error', 'chaos: crash mode request counted', {
      method,
      path,
      status: 0,
      duration_ms: 0,
      request_count: crashRequestCount,
      limit,
    });
    if (crashRequestCount >= limit) {
      logJson('error', 'chaos: crashing on purpose', { method, path, status: 0, duration_ms: 0 });
      process.exit(1);
    }
    return { shortCircuit: false };
  }

  // memory_leak is handled by the background interval above.
  return { shortCircuit: false };
}

// ---------------------------------------------------------------------------
// Express app
// ---------------------------------------------------------------------------

const app = express();
app.use(express.json());

app.use((req, res, next) => {
  const start = process.hrtime.bigint();
  res.on('finish', () => {
    const end = process.hrtime.bigint();
    const durationSeconds = Number(end - start) / 1e9;
    const path = req.path;
    httpRequestsTotal.labels(req.method, path, String(res.statusCode), APP_NAME).inc();
    httpRequestDuration.labels(req.method, path, APP_NAME).observe(durationSeconds);
    logJson(res.statusCode < 500 ? 'info' : 'error', 'request handled', {
      method: req.method,
      path,
      status: res.statusCode,
      duration_ms: Math.round(durationSeconds * 1000 * 100) / 100,
    });
  });
  next();
});

app.get('/health', (req, res) => {
  res.json({ status: 'ok' });
});

app.get('/metrics', async (req, res) => {
  res.set('Content-Type', register.contentType);
  res.end(await register.metrics());
});

app.get('/chaos/status', (req, res) => {
  res.json({ ...chaosState });
});

app.post('/chaos/enable', (req, res) => {
  const body = req.body || {};
  const mode = body.mode || 'none';
  let intensity = body.intensity;
  if (intensity === undefined || intensity === null) {
    intensity = CHAOS_DEFAULT_INTENSITY[mode] !== undefined ? CHAOS_DEFAULT_INTENSITY[mode] : 0;
  }
  chaosState.enabled = true;
  chaosState.mode = mode;
  chaosState.intensity = Number(intensity);
  crashRequestCount = 0;
  logJson('info', 'chaos: enabled', {
    method: 'POST',
    path: '/chaos/enable',
    status: 200,
    duration_ms: 0,
    mode,
    intensity,
  });
  res.json({ ...chaosState });
});

app.post('/chaos/disable', (req, res) => {
  chaosState.enabled = false;
  chaosState.mode = 'none';
  chaosState.intensity = 0;
  crashRequestCount = 0;
  memoryLeakBuffer.length = 0;
  logJson('info', 'chaos: disabled', {
    method: 'POST',
    path: '/chaos/disable',
    status: 200,
    duration_ms: 0,
  });
  res.json({ ...chaosState });
});

// ---------------------------------------------------------------------------
// Business endpoints
// ---------------------------------------------------------------------------

const FAKE_PAYMENTS = {};

app.post('/payments', async (req, res) => {
  await tracer.startActiveSpan('payments-api.handle_payments', async (span) => {
    try {
      const chaos = await applyChaos('POST', '/payments');
      if (chaos.shortCircuit) {
        res.status(chaos.status).json(chaos.body);
        return;
      }
      const { orderId, amount } = req.body || {};
      const id = `pay-${Math.random().toString(16).slice(2, 10)}`;
      const payment = {
        id,
        orderId: orderId !== undefined ? orderId : null,
        amount: amount !== undefined ? amount : null,
        status: 'confirmed',
      };
      FAKE_PAYMENTS[id] = payment;
      res.json(payment);
    } finally {
      span.end();
    }
  });
});

app.get('/payments/:id', async (req, res) => {
  await tracer.startActiveSpan('payments-api.handle_payments', async (span) => {
    try {
      const chaos = await applyChaos('GET', '/payments/:id');
      if (chaos.shortCircuit) {
        res.status(chaos.status).json(chaos.body);
        return;
      }
      const payment = FAKE_PAYMENTS[req.params.id];
      if (!payment) {
        res.status(404).json({ error: 'payment not found' });
        return;
      }
      res.json(payment);
    } finally {
      span.end();
    }
  });
});

app.listen(PORT, () => {
  logJson('info', `${APP_NAME} listening on port ${PORT}`, {
    method: '',
    path: '',
    status: 0,
    duration_ms: 0,
  });
});
