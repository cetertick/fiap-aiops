# FIAP AIOps Lab - Microservices de demonstração

Três microsserviços simples, cada um em uma linguagem diferente, usados na aula
de observabilidade + detecção de anomalias + auto-remediação. Todos seguem o
mesmo contrato de instrumentação (health, metrics, chaos, logs JSON, tracing),
para que Prometheus, Grafana, o agente de remediação e o gerador de postmortem
funcionem do mesmo jeito contra qualquer um dos três.

## Os apps

| App | Linguagem/Framework | Porta | Endpoints de negócio |
|---|---|---|---|
| `orders-api` | Python 3.12, FastAPI + uvicorn | 8000 | `GET /orders`, `POST /orders` |
| `payments-api` | Node.js 20, Express | 8001 | `POST /payments`, `GET /payments/:id` |
| `inventory-api` | Go 1.22, Gin | 8002 | `GET /inventory`, `POST /inventory/reserve` |

Cada um também expõe, de forma idêntica:

- `GET /health` → `{"status":"ok"}`
- `GET /metrics` → métricas Prometheus (`http_requests_total`, `http_request_duration_seconds`)
- `GET /chaos/status`, `POST /chaos/enable`, `POST /chaos/disable` → painel de caos
- Logs JSON estruturados no stdout (um objeto por linha)
- Tracing OpenTelemetry (OTLP/gRPC) nos endpoints de negócio

O caos (latência, erros HTTP, vazamento de memória, crash) só afeta os
endpoints de negócio — `/health`, `/metrics` e `/chaos/*` nunca são afetados,
para que o Kubernetes sempre consiga checar a saúde do pod mesmo com caos
ativo (exceto quando o próprio caos é "crash" ou "memory_leak", que matam o
processo/container de propósito).

## Rodando localmente (build + run com Docker)

```bash
# orders-api
cd apps/orders-api
docker build -t orders-api:local .
docker run --rm -p 8000:8000 orders-api:local

# payments-api
cd apps/payments-api
docker build -t payments-api:local .
docker run --rm -p 8001:8001 payments-api:local

# inventory-api
cd apps/inventory-api
docker build -t inventory-api:local .
docker run --rm -p 8002:8002 inventory-api:local
```

Teste rápido de cada um:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/orders

curl http://localhost:8001/health
curl -X POST http://localhost:8001/payments -H 'Content-Type: application/json' \
  -d '{"orderId":"ord-1","amount":99.90}'

curl http://localhost:8002/health
curl http://localhost:8002/inventory
```

Também é possível pré-configurar o caos já no `docker run` via env vars
(sem precisar chamar o endpoint HTTP):

```bash
docker run --rm -p 8000:8000 \
  -e CHAOS_ENABLED=true -e CHAOS_MODE=latency -e CHAOS_INTENSITY=1500 \
  orders-api:local
```

## Port-forward no Kubernetes (para testar durante a aula)

Depois que os Deployments/Services estiverem no cluster, no namespace
`aiops-lab`:

```bash
kubectl port-forward svc/orders-api    -n aiops-lab 8000:8000
kubectl port-forward svc/payments-api  -n aiops-lab 8001:8001
kubectl port-forward svc/inventory-api -n aiops-lab 8002:8002
```

(abra um terminal por serviço, ou rode em background com `&`)

## Cheat-sheet do caos para a demo em sala

Troque `<porta>` pela porta do serviço que você está demonstrando (8000 =
orders-api, 8001 = payments-api, 8002 = inventory-api). Os mesmos comandos
funcionam via port-forward (`localhost:<porta>`) ou direto no IP do pod.

```bash
# ver o estado atual do caos
curl http://localhost:<porta>/chaos/status

# habilitar latência alta (sleep de 3000ms em cada request de negócio)
curl -X POST http://localhost:<porta>/chaos/enable \
  -H 'Content-Type: application/json' \
  -d '{"mode":"latency","intensity":3000}'

# habilitar taxa de erro (60% das requisições de negócio retornam HTTP 500)
curl -X POST http://localhost:<porta>/chaos/enable \
  -H 'Content-Type: application/json' \
  -d '{"mode":"http_errors","intensity":60}'

# vazamento de memória (cresce ~1MB/s; com o limit de 256Mi do pod,
# o OOMKill deve acontecer em ~1-2 minutos)
curl -X POST http://localhost:<porta>/chaos/enable \
  -H 'Content-Type: application/json' \
  -d '{"mode":"memory_leak","intensity":0}'

# crash após N requisições de negócio (aqui, 3) -> CrashLoopBackOff
curl -X POST http://localhost:<porta>/chaos/enable \
  -H 'Content-Type: application/json' \
  -d '{"mode":"crash","intensity":3}'

# desligar o caos (volta ao normal)
curl -X POST http://localhost:<porta>/chaos/disable
```

Se nenhum `intensity` for enviado no `/chaos/enable`, cada modo usa um valor
padrão sensato: `latency` = 2000ms, `http_errors` = 50%, `crash` = 5
requisições, `memory_leak` = ignorado (sempre ~1MB/s).

As mesmas chaves também podem ser pré-configuradas direto no manifesto do
Deployment (`CHAOS_ENABLED`, `CHAOS_MODE`, `CHAOS_INTENSITY`), mas os
endpoints HTTP sempre sobrescrevem em runtime — essa é a alavanca que o
instrutor usa ao vivo, sem precisar fazer redeploy.
