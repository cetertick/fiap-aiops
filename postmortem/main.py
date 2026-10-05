"""
Postmortem Generator — serviço FastAPI para o laboratório de AIOps.

Fluxo:
  1. Grafana dispara um alerta e chama POST /webhook/grafana com o payload
     padrão do unified alerting.
  2. Para cada alerta com status "firing", coletamos contexto de
     observabilidade (Prometheus + Loki), chamamos a API da Anthropic para
     gerar um RCA estruturado em Markdown, renderizamos em PDF e publicamos
     no canal do Discord configurado.
  3. Sempre respondemos 200 ao Grafana, mesmo em caso de falha parcial —
     devolver 5xx faria o Grafana considerar a notificação como falha e
     re-tentar / gerar alarme adicional sobre a própria notificação.

POST /debug/simulate roda o mesmo pipeline manualmente, útil para testar o
serviço antes (ou durante) a aula, sem esperar um alerta real do Grafana.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, Request
from pydantic import BaseModel

from config import ANTHROPIC_API_KEY, DISCORD_WEBHOOK_URL
from discord_notify import send_pdf_to_discord
from llm import generate_postmortem_markdown
from observability import get_error_logs_excerpt, get_metrics_snapshot
from pdf_render import render_postmortem_pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("postmortem.main")

app = FastAPI(
    title="Postmortem Generator",
    description="Gera postmortems/RCA automáticos a partir de alertas do Grafana usando a API da Anthropic.",
)


@app.on_event("startup")
def _warn_on_missing_config() -> None:
    if not ANTHROPIC_API_KEY:
        logger.warning(
            "ANTHROPIC_API_KEY não configurado — chamadas à API da Anthropic vão falhar "
            "(isso é esperado só se o Secret ainda não foi criado)."
        )
    if not DISCORD_WEBHOOK_URL:
        logger.warning(
            "DISCORD_WEBHOOK_URL não configurado — o envio ao Discord será pulado."
        )


class SimulateRequest(BaseModel):
    app: str
    alertname: str
    summary: Optional[str] = None
    description: Optional[str] = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _process_single_alert(
    alertname: str,
    app_name: str,
    summary: str,
    description: str,
    starts_at: str,
) -> dict[str, Any]:
    """Roda o pipeline completo (contexto -> LLM -> PDF -> Discord) para um alerta."""
    result: dict[str, Any] = {
        "alertname": alertname,
        "app": app_name,
        "postmortem_generated": False,
        "discord_sent": False,
        "error": None,
    }

    pdf_path: Optional[str] = None
    try:
        logger.info("Coletando contexto de observabilidade (app=%s)", app_name)
        metrics_snapshot = get_metrics_snapshot(app_name)
        log_excerpt = get_error_logs_excerpt(app_name)

        logger.info("Chamando a API da Anthropic para gerar o RCA (alert=%s, app=%s)", alertname, app_name)
        markdown = generate_postmortem_markdown(
            alertname=alertname,
            app=app_name,
            summary=summary,
            description=description,
            starts_at=starts_at,
            metrics_snapshot=metrics_snapshot,
            log_excerpt=log_excerpt,
        )
        result["postmortem_generated"] = True

        logger.info("Renderizando PDF do postmortem (alert=%s)", alertname)
        pdf_path = render_postmortem_pdf(markdown, alertname, app_name, summary)

        logger.info("Enviando PDF ao Discord (alert=%s)", alertname)
        sent, message = send_pdf_to_discord(pdf_path, alertname, app_name)
        result["discord_sent"] = sent
        result["discord_message"] = message

    except Exception as exc:  # noqa: BLE001 - nunca deixamos isso propagar para o Grafana
        logger.exception("Falha ao processar alerta %s/%s", alertname, app_name)
        result["error"] = str(exc)

    finally:
        if pdf_path:
            try:
                os.remove(pdf_path)
            except OSError:
                pass

    return result


def _extract_firing_alerts(payload: dict) -> list[dict]:
    """Extrai, de forma defensiva, os alertas com status 'firing' do payload do Grafana."""
    alerts = payload.get("alerts")
    if not isinstance(alerts, list):
        return []

    firing: list[dict] = []
    default_status = payload.get("status", "firing")
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        status = alert.get("status", default_status)
        if status == "firing":
            firing.append(alert)
    return firing


@app.post("/webhook/grafana")
async def grafana_webhook(request: Request) -> dict:
    """
    Recebe o webhook do Grafana (unified alerting). Sempre retorna 200 —
    erros são logados e refletidos no campo `error` de cada item processado,
    nunca propagados como status HTTP de falha.
    """
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        logger.error("Payload do Grafana não é um JSON válido: %s", exc)
        return {"status": "ignored", "reason": "invalid_json", "processed": []}

    if not isinstance(payload, dict):
        logger.error("Payload do Grafana não é um objeto JSON: %r", type(payload))
        return {"status": "ignored", "reason": "payload_not_object", "processed": []}

    firing_alerts = _extract_firing_alerts(payload)
    if not firing_alerts:
        logger.info("Webhook recebido sem alertas em status 'firing'; nada a processar.")
        return {"status": "ok", "processed": []}

    common_labels = payload.get("commonLabels") or {}
    default_summary = payload.get("message") or ""

    results = []
    for alert in firing_alerts:
        labels = alert.get("labels") or {}
        annotations = alert.get("annotations") or {}

        alertname = labels.get("alertname") or "AlertaDesconhecido"
        app_name = labels.get("app") or common_labels.get("app") or "app-desconhecida"
        summary = annotations.get("summary") or default_summary
        description = annotations.get("description") or ""
        starts_at = alert.get("startsAt") or datetime.now(timezone.utc).isoformat()

        logger.info("Processando alerta firing: alertname=%s app=%s", alertname, app_name)
        result = _process_single_alert(alertname, app_name, summary, description, starts_at)
        results.append(result)

    return {"status": "ok", "processed": results}


@app.post("/debug/simulate")
def debug_simulate(req: SimulateRequest) -> dict:
    """
    Endpoint de teste manual: roda o pipeline completo sem depender de um
    alerta real do Grafana. Útil para validar a configuração (chaves,
    conectividade com Prometheus/Loki/Discord) antes ou durante a aula.
    """
    summary = req.summary or f"[SIMULAÇÃO] Alerta {req.alertname} disparado para a aplicação {req.app}."
    description = (
        req.description
        or "Alerta disparado manualmente via /debug/simulate, para fins de teste do pipeline de postmortem."
    )
    starts_at = datetime.now(timezone.utc).isoformat()

    logger.info("Simulação manual: alertname=%s app=%s", req.alertname, req.app)
    result = _process_single_alert(req.alertname, req.app, summary, description, starts_at)
    return {"status": "ok", "processed": [result]}
