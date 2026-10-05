"""
Envio do PDF de postmortem para um canal do Discord via webhook.

Discord webhooks aceitam multipart/form-data com uma parte `payload_json`
(conteúdo da mensagem) e uma parte `files[0]` (o arquivo anexado).
"""
import json
import logging
import os

import requests

from config import DISCORD_MAX_FILE_BYTES, DISCORD_WEBHOOK_URL, HTTP_TIMEOUT_SECONDS

logger = logging.getLogger("postmortem.discord")


def send_pdf_to_discord(pdf_path: str, alertname: str, app: str) -> tuple[bool, str]:
    """
    Faz upload do PDF para o canal do Discord configurado via
    DISCORD_WEBHOOK_URL.

    Retorna (sucesso: bool, mensagem: str). Nunca lança exceção — quem chama
    decide o que fazer com o resultado (o endpoint HTTP sempre responde 200).
    """
    if not DISCORD_WEBHOOK_URL:
        msg = "DISCORD_WEBHOOK_URL não configurado; pulando envio ao Discord."
        logger.warning(msg)
        return False, msg

    try:
        file_size = os.path.getsize(pdf_path)
    except OSError as exc:
        msg = f"Não foi possível ler o arquivo PDF gerado: {exc}"
        logger.error(msg)
        return False, msg

    if file_size > DISCORD_MAX_FILE_BYTES:
        msg = (
            f"PDF gerado ({file_size} bytes) excede o limite de upload do "
            f"webhook do Discord ({DISCORD_MAX_FILE_BYTES} bytes); não enviado."
        )
        logger.error(msg)
        return False, msg

    content = f"📋 Postmortem gerado automaticamente — **{alertname}** em **{app}**"
    payload_json = json.dumps({"content": content})

    try:
        with open(pdf_path, "rb") as f:
            filename = f"postmortem_{app}_{alertname}.pdf".replace(" ", "_")
            files = {
                "files[0]": (filename, f, "application/pdf"),
            }
            data = {
                "payload_json": payload_json,
            }
            resp = requests.post(
                DISCORD_WEBHOOK_URL,
                data=data,
                files=files,
                timeout=HTTP_TIMEOUT_SECONDS * 4,  # upload pode levar mais tempo que queries
            )
    except requests.RequestException as exc:
        msg = f"Falha de rede ao enviar PDF para o Discord: {exc}"
        logger.error(msg)
        return False, msg

    if resp.status_code not in (200, 204):
        msg = f"Discord respondeu com status {resp.status_code}: {resp.text[:500]}"
        logger.error(msg)
        return False, msg

    return True, "PDF enviado ao Discord com sucesso."
