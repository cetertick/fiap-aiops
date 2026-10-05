"""
Coleta de contexto de observabilidade (Prometheus + Loki) para alimentar o
prompt do Claude.

Cada função aqui é defensiva: se o Prometheus/Loki estiver fora do ar, ou
devolver algo inesperado, nós devolvemos um placeholder em vez de propagar a
exceção — o pipeline de postmortem não deve falhar por falta de métricas.
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from config import (
    CONTEXT_WINDOW_MINUTES,
    HTTP_TIMEOUT_SECONDS,
    LOKI_URL,
    NAMESPACE,
    PLACEHOLDER_UNAVAILABLE,
    PROMETHEUS_URL,
)

logger = logging.getLogger("postmortem.observability")


def _prom_query_range(promql: str, start: float, end: float, step: str = "60s") -> list[dict] | None:
    """Executa uma query_range no Prometheus. Retorna None em qualquer falha."""
    try:
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query_range",
            params={"query": promql, "start": start, "end": end, "step": step},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            logger.warning("Prometheus query não teve status=success: %s", data)
            return None
        return data.get("data", {}).get("result", [])
    except Exception as exc:  # noqa: BLE001 - queremos capturar qualquer falha de rede/parsing
        logger.warning("Falha ao consultar Prometheus (%s): %s", promql, exc)
        return None


def _series_to_map(result: list[dict] | None) -> dict[float, float]:
    """Converte o resultado de uma série única do Prometheus em {timestamp: valor}."""
    out: dict[float, float] = {}
    if not result:
        return out
    try:
        values = result[0].get("values", [])
        for ts, val in values:
            try:
                out[float(ts)] = float(val)
            except (TypeError, ValueError):
                continue
    except (IndexError, AttributeError, KeyError):
        pass
    return out


def get_metrics_snapshot(app: str) -> str:
    """
    Busca request rate, error rate (%) e p95 de latência (ms) para `app` nos
    últimos CONTEXT_WINDOW_MINUTES minutos, e formata como uma tabela de texto
    compacta: timestamp | request_rate | error_rate_pct | p95_latency_ms.

    Se o Prometheus estiver inacessível ou não houver dados, retorna um texto
    de placeholder — nunca lança exceção.
    """
    now = time.time()
    start = now - CONTEXT_WINDOW_MINUTES * 60
    step = "60s"

    rate_query = f'sum(rate(http_requests_total{{app="{app}"}}[2m]))'
    error_query = (
        f'sum(rate(http_requests_total{{app="{app}",status=~"5.."}}[2m])) / '
        f'clamp_min(sum(rate(http_requests_total{{app="{app}"}}[2m])), 1e-9) * 100'
    )
    p95_query = (
        f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket'
        f'{{app="{app}"}}[2m])) by (le)) * 1000'
    )

    rate_series = _series_to_map(_prom_query_range(rate_query, start, now, step))
    error_series = _series_to_map(_prom_query_range(error_query, start, now, step))
    p95_series = _series_to_map(_prom_query_range(p95_query, start, now, step))

    if not rate_series and not error_series and not p95_series:
        return f"Métricas do Prometheus: {PLACEHOLDER_UNAVAILABLE} para app={app}."

    all_timestamps = sorted(set(rate_series) | set(error_series) | set(p95_series))
    lines = ["timestamp            | request_rate | error_rate_pct | p95_latency_ms"]
    lines.append("-" * 70)
    for ts in all_timestamps:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        rr = rate_series.get(ts)
        er = error_series.get(ts)
        p95 = p95_series.get(ts)
        rr_s = f"{rr:.2f}" if rr is not None else "n/d"
        er_s = f"{er:.2f}" if er is not None else "n/d"
        p95_s = f"{p95:.1f}" if p95 is not None else "n/d"
        lines.append(f"{dt} | {rr_s:>12} | {er_s:>14} | {p95_s:>14}")

    return "\n".join(lines)


def get_error_logs_excerpt(app: str, max_lines: int = 50) -> str:
    """
    Busca as últimas ~max_lines linhas de log do Loki para o namespace do lab,
    filtra no cliente por `app` e por `level=error` (de forma tolerante, já que
    não garantimos que o Promtail rotule por app), e retorna um texto formatado.

    Defensivo: qualquer problema de rede/parsing retorna um placeholder.
    """
    now_ns = time.time_ns()
    start_ns = now_ns - CONTEXT_WINDOW_MINUTES * 60 * 1_000_000_000

    logql = f'{{namespace="{NAMESPACE}"}}'

    try:
        resp = requests.get(
            f"{LOKI_URL}/loki/api/v1/query_range",
            params={
                "query": logql,
                "start": start_ns,
                "end": now_ns,
                "limit": 1000,
                "direction": "backward",
            },
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            logger.warning("Loki query não teve status=success: %s", data)
            return f"Logs do Loki: {PLACEHOLDER_UNAVAILABLE} para app={app}."

        streams = data.get("data", {}).get("result", [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falha ao consultar Loki: %s", exc)
        return f"Logs do Loki: {PLACEHOLDER_UNAVAILABLE} para app={app}."

    candidate_lines: list[tuple[int, str]] = []
    for stream in streams:
        for entry in stream.get("values", []):
            try:
                ts_ns, line = entry
            except (ValueError, TypeError):
                continue
            candidate_lines.append((int(ts_ns), line))

    if not candidate_lines:
        return f"Logs do Loki: nenhuma linha encontrada no namespace {NAMESPACE} na janela recente."

    # Ordena do mais recente para o mais antigo (já pedimos "backward", mas
    # streams diferentes podem intercalar fora de ordem).
    candidate_lines.sort(key=lambda t: t[0], reverse=True)

    relevant: list[str] = []
    for _, line in candidate_lines:
        line_lower = line.lower()
        if app.lower() not in line_lower:
            continue
        # Tenta parsear como JSON estruturado; se não for JSON, faz match textual.
        is_error = False
        parsed: dict[str, Any] | None = None
        try:
            parsed = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            parsed = None

        if parsed is not None:
            level = str(parsed.get("level", "")).lower()
            is_error = level in ("error", "err", "critical", "fatal")
        else:
            is_error = "error" in line_lower or '"level":"error"' in line_lower

        if is_error:
            relevant.append(line)
        if len(relevant) >= max_lines:
            break

    # Se não encontramos nenhuma linha de erro específica da app, caímos para
    # qualquer linha mencionando a app (mais contexto é melhor que nenhum).
    if not relevant:
        for _, line in candidate_lines:
            if app.lower() in line.lower():
                relevant.append(line)
            if len(relevant) >= max_lines:
                break

    if not relevant:
        return (
            f"Logs do Loki: nenhuma linha mencionando app={app} encontrada "
            f"entre as últimas {len(candidate_lines)} linhas do namespace {NAMESPACE}."
        )

    # Mantém a ordem cronológica (mais antiga primeiro) no texto final.
    relevant.reverse()
    excerpt = "\n".join(relevant[-max_lines:])
    # Trunca de forma defensiva caso as linhas sejam muito grandes.
    if len(excerpt) > 8000:
        excerpt = excerpt[-8000:]
    return excerpt
