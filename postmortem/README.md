# Postmortem Generator

Serviço FastAPI que recebe o webhook de alerta do Grafana, coleta contexto de
observabilidade (Prometheus + Loki), gera um postmortem/RCA estruturado em
português usando a API da Anthropic (Claude), renderiza o resultado em PDF e
publica no Discord.

Namespace: `aiops-lab`. Deployment/Service: `postmortem-service`, porta `8080`.

## Arquitetura (resumo)

```
Grafana (alerta) --webhook--> POST /webhook/grafana
                                   │
                                   ├─> Prometheus: métricas (request rate, error rate, p95)
                                   ├─> Loki: últimas linhas de log de erro da app
                                   ├─> Anthropic API: gera o RCA em Markdown (pt-BR)
                                   ├─> fpdf2: renderiza o Markdown em PDF
                                   └─> Discord webhook: posta o PDF no canal
```

Endpoints:
- `POST /webhook/grafana` — recebido pelo Grafana. Sempre responde `200`
  (mesmo em falha parcial), para não fazer o Grafana re-tentar/alarmar sobre
  a notificação em si.
- `POST /debug/simulate` — roda o pipeline completo manualmente, sem esperar
  um alerta real. Corpo: `{"app": "orders-api", "alertname": "HighErrorRate"}`.
- `GET /health` — healthcheck (`{"status": "ok"}`).

## Secrets necessários

O Deployment espera um Secret chamado `postmortem-secrets` no namespace
`aiops-lab`, com as chaves:

- `ANTHROPIC_API_KEY` — chave da API da Anthropic.
- `DISCORD_WEBHOOK_URL` — URL do webhook do canal do Discord onde o PDF será
  publicado.

Veja `k8s/secret-template.yaml` para o formato esperado (é só um template
comentado — **não** contém segredos reais e não deve ser aplicado como está).

### Como criar o Secret

```bash
kubectl create namespace aiops-lab --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic postmortem-secrets \
  -n aiops-lab \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxx \
  --from-literal=DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/XXXXXXXXXXXX/YYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYY
```

Para atualizar os valores depois de criado:

```bash
kubectl delete secret postmortem-secrets -n aiops-lab
# e rode o comando `kubectl create secret generic ...` novamente com os novos valores
```

### Como obter uma API key da Anthropic

1. Acesse https://console.anthropic.com e faça login (ou crie uma conta).
2. Vá em **API Keys** (menu de configurações da organização).
3. Clique em **Create Key**, dê um nome (ex.: `fiap-aiops-lab`) e copie o
   valor gerado (começa com `sk-ant-...`) — ele só é exibido uma vez.
4. Garanta que a organização tenha créditos/billing configurado, ou as
   chamadas à API vão falhar com erro de autenticação/quota.

### Como obter a URL do webhook do Discord

1. No canal do Discord onde o PDF deve ser postado, abra
   **Configurações do Canal → Integrações → Webhooks**.
2. Clique em **Novo Webhook**, dê um nome (ex.: `postmortem-bot`) e copie a
   **URL do Webhook**.

## Deploy

```bash
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

A imagem (`ghcr.io/cetertick/fiap-aiops-postmortem-service:latest`) é
publicada pelo pipeline de CI/CD do repositório. Para rodar localmente sem
Kubernetes, veja a seção abaixo.

## Rodando localmente

```bash
cd postmortem
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxx
export DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/XXXX/YYYY
# Opcional — se o Prometheus/Loki não estiverem acessíveis localmente, o
# serviço simplesmente usa "dados indisponíveis" nessas seções do prompt.
export PROMETHEUS_URL=http://localhost:9090
export LOKI_URL=http://localhost:3100

uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

### Testando com um curl simulando o webhook do Grafana

```bash
curl -X POST http://localhost:8080/webhook/grafana \
  -H "Content-Type: application/json" \
  -d '{
    "receiver": "postmortem-webhook",
    "status": "firing",
    "alerts": [
      {
        "status": "firing",
        "labels": {
          "alertname": "HighErrorRate",
          "app": "orders-api",
          "severity": "critical"
        },
        "annotations": {
          "summary": "Taxa de erro 5xx acima de 10% em orders-api",
          "description": "O endpoint /orders está retornando 500 para mais de 10% das requisições nos últimos 5 minutos."
        },
        "startsAt": "2026-10-05T14:32:00Z",
        "endsAt": "0001-01-01T00:00:00Z",
        "generatorURL": "http://grafana.aiops-lab.svc.cluster.local:3000/alerting/grafana/abc123/view",
        "fingerprint": "abc123def456"
      }
    ],
    "groupLabels": {"alertname": "HighErrorRate"},
    "commonLabels": {"app": "orders-api"},
    "title": "[FIRING:1] HighErrorRate orders-api",
    "message": "Taxa de erro 5xx acima de 10% em orders-api"
  }'
```

Resposta esperada (200, mesmo em caso de falha parcial em algum passo):

```json
{
  "status": "ok",
  "processed": [
    {
      "alertname": "HighErrorRate",
      "app": "orders-api",
      "postmortem_generated": true,
      "discord_sent": true,
      "discord_message": "PDF enviado ao Discord com sucesso.",
      "error": null
    }
  ]
}
```

### Testando com `/debug/simulate` (atalho para a aula)

Útil para um teste rápido ao vivo, sem precisar esperar o Prometheus/Grafana
realmente disparar um alerta:

```bash
curl -X POST http://localhost:8080/debug/simulate \
  -H "Content-Type: application/json" \
  -d '{"app": "orders-api", "alertname": "HighErrorRate"}'
```

Esse endpoint roda o pipeline completo (contexto de observabilidade → Claude
→ PDF → Discord) com um resumo/descrição padrão gerados automaticamente, caso
não sejam informados no corpo da requisição. Também é possível sobrescrever
`summary` e `description`:

```bash
curl -X POST http://localhost:8080/debug/simulate \
  -H "Content-Type: application/json" \
  -d '{
    "app": "payments-api",
    "alertname": "HighLatencyP95",
    "summary": "P95 de latência acima de 2s em payments-api",
    "description": "Latência do endpoint /payments degradou após deploy da versão v1.4.0."
  }'
```

## Observações de projeto

- Toda chamada a Prometheus/Loki é feita de forma defensiva: se o serviço
  estiver fora do ar ou não retornar dados, o pipeline segue com placeholders
  ("dados indisponíveis") em vez de falhar a geração do postmortem.
- O serviço nunca retorna 5xx para o Grafana — falhas são logadas e
  refletidas no campo `error` de cada item do array `processed` na resposta.
- A renderização de PDF usa `fpdf2` (puro Python) com um subconjunto simples
  de Markdown (`#`/`##`/`###`, bullets `- `/`* `, parágrafos), evitando
  dependências de sistema como wkhtmltopdf/weasyprint na imagem Docker.
- Limite de upload do Discord (8MB) é verificado antes do envio; se
  excedido, o erro é logado e refletido na resposta, sem derrubar o restante
  do pipeline.
