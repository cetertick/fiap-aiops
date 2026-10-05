"""
Integração com a API da Anthropic: monta o prompt do postmortem e chama o
modelo Claude para gerar o RCA em Markdown.
"""
import logging

import anthropic

from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

logger = logging.getLogger("postmortem.llm")

SYSTEM_PROMPT = """\
Você é um Site Reliability Engineer (SRE) sênior, especialista em escrever \
postmortems/RCAs (Root Cause Analysis) claros e objetivos em português do Brasil.

IMPORTANTE: este é um incidente SIMULADO, gerado em um laboratório educacional \
de AIOps (uma aula universitária). Os dados de métricas e logs vêm de uma \
demonstração controlada, não de um sistema de produção real. Você pode e deve \
escrever o RCA normalmente, com causas raízes e ações concretas, sem ressalvas \
de que "não é possível confirmar sem acesso a sistemas reais" — assuma o papel \
de SRE responsável pela análise deste incidente de laboratório.

Formato de saída: Markdown, usando EXATAMENTE estas seções, nesta ordem, com \
estes títulos (incluindo o nível de cabeçalho ##):

## Resumo
## Linha do Tempo
## Causa Raiz
## Impacto
## Lições Aprendidas
## Ações Preventivas

Seja objetivo e técnico. O texto completo deve ter entre 400 e 600 palavras. \
Não inclua nenhum texto antes do primeiro cabeçalho ou depois da última seção \
(sem introduções do tipo "Aqui está o postmortem:" e sem conclusões fora das \
seções pedidas).\
"""


def _build_user_prompt(
    alertname: str,
    app: str,
    summary: str,
    description: str,
    starts_at: str,
    metrics_snapshot: str,
    log_excerpt: str,
) -> str:
    return f"""\
Gere um postmortem/RCA para o seguinte alerta disparado no Grafana.

### Dados do alerta
- Nome do alerta: {alertname}
- Aplicação afetada: {app}
- Início (startsAt): {starts_at}
- Resumo (summary): {summary}
- Descrição (description): {description}

### Snapshot de métricas (Prometheus, últimos minutos antes/durante o alerta)
```
{metrics_snapshot}
```

### Trecho de logs de erro (Loki, linhas mais recentes relevantes)
```
{log_excerpt}
```

Escreva o RCA completo seguindo exatamente as seções e o formato definidos \
nas instruções do sistema.\
"""


def generate_postmortem_markdown(
    alertname: str,
    app: str,
    summary: str,
    description: str,
    starts_at: str,
    metrics_snapshot: str,
    log_excerpt: str,
) -> str:
    """
    Chama a API da Anthropic para gerar o Markdown do postmortem.

    Levanta a exceção original em caso de falha — quem chama decide como
    tratar (no main.py isso é capturado e tratado de forma defensiva, sem
    derrubar a resposta ao Grafana).
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    user_prompt = _build_user_prompt(
        alertname=alertname,
        app=app,
        summary=summary,
        description=description,
        starts_at=starts_at,
        metrics_snapshot=metrics_snapshot,
        log_excerpt=log_excerpt,
    )

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text_parts = [block.text for block in response.content if block.type == "text"]
    markdown = "\n".join(text_parts).strip()

    if not markdown:
        raise RuntimeError("A API da Anthropic retornou uma resposta vazia.")

    return markdown
