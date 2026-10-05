# FIAP AIOps Lab — Observabilidade, Detecção de Anomalias e Auto-Remediação

Laboratório hands-on para a aula de **AIOps** da pós-graduação FIAP TECH
(trilha Arquitetura Cloud & DevOps), duração **1h20**. Sobe do zero, em um
cluster EKS descartável (AWS Academy Learner Lab), um ciclo completo de
AIOps:

```
chaos injetado na app  →  Prometheus/Loki/Tempo observam
        →  Grafana detecta anomalia  →  dispara 2 caminhos em paralelo:
             1) Discord (alerta humano imediato)
             2) postmortem-service → Claude API → PDF de RCA → Discord
        →  ao mesmo tempo, o aiops-agent detecta a mesma anomalia via
           Prometheus/K8s API e REMEDIA sozinho (restart de pod, scale-up,
           "circuit breaker" desligando o chaos) e registra tudo via
           Kubernetes Events + /actions
```

Tudo é implantado via **ArgoCD (GitOps)**, com CI/CD no **GitHub Actions**
(Trivy + SonarCloud) publicando imagens no **GitHub Container Registry**.

> Todo o conteúdo técnico comentado está em português, já que a turma é em
> português. Nomes de recursos (clusters, namespaces, serviços) seguem o
> inglês técnico padrão de mercado.

---

## 1. Arquitetura

```
┌─────────────────────────────── AWS (Academy Learner Lab) ───────────────────────────────┐
│                                                                                            │
│  VPC (2 AZs, subnets públicas+privadas)                                                   │
│   └── EKS Cluster "aiops-lab-eks"                                                         │
│        └── Node Group "AIOPS-workers" (2+ nós, label node-group=AIOPS)                    │
│             ├── ns argocd         → ArgoCD (GitOps, UI via ALB)                           │
│             ├── ns monitoring     → kube-prometheus-stack (Prometheus+Grafana+Alertmgr),  │
│             │                       Loki+Promtail, Tempo, OpenTelemetry Collector         │
│             └── ns aiops-lab      → orders-api, payments-api, inventory-api (com chaos    │
│                                      injection embutido) + aiops-agent + postmortem-service│
│                                                                                            │
│  ALB (AWS Load Balancer Controller) → expõe a UI do ArgoCD                                │
│  ECR (opcional) — CI/CD usa GHCR por padrão                                               │
└────────────────────────────────────────────────────────────────────────────────────────┘

GitHub Actions (CI/CD)                    Discord                      Claude API (Anthropic)
  Trivy (scan) + SonarCloud (SAST)   ←────── alertas e PDFs ──────→   geração do postmortem
  build + push → ghcr.io
```

### Componentes e onde encontrá-los

| Componente | Pasta | O que faz |
|---|---|---|
| Infraestrutura (Terraform) | `/terraform` | VPC, EKS, node group "AIOPS", ALB Controller, ECR |
| 3 apps de exemplo | `/apps`, manifests em `/k8s/apps` | FastAPI, Express, Gin — health, métricas, **chaos injection** |
| Pipeline CI/CD | `/.github/workflows/ci.yml`, `sonar-project.properties` | Trivy + SonarCloud, build/push para GHCR |
| Observabilidade | `/k8s/observability` | kube-prometheus-stack, Loki, Tempo, OTel Collector, dashboards, alertas |
| GitOps | `/k8s/argocd` | App-of-apps, Applications por componente, Ingress ALB |
| Agente AIOps | `/aiops-agent` | Detecção + auto-remediação + auditoria |
| Postmortem automatizado | `/postmortem` | Webhook do Grafana → Claude API → PDF → Discord |

---

## 2. Pré-requisitos (fazer ANTES da aula)

**Contas/credenciais:**
- [ ] AWS Academy Learner Lab iniciado ("Start Lab" com status verde).
- [ ] Repositório GitHub `cetertick/fiap-aiops` (ou fork) com Actions habilitado.
- [ ] Token do SonarCloud (`SONAR_TOKEN`) configurado como secret do repo — veja `sonar-project.properties`.
- [ ] Webhook do Discord criado em um canal de teste (Configurações do canal → Integrações → Webhooks).
- [ ] Chave de API da Anthropic (`console.anthropic.com`) para o `postmortem-service`.

**Ferramentas instaladas na máquina do instrutor:**
`terraform >= 1.6`, `aws` CLI v2, `kubectl`, `helm`, `docker`, `git`.

**Pré-aquecimento recomendado (10 min antes da turma entrar):**
1. Iniciar o Learner Lab e exportar as credenciais AWS (expiram em ~4h — ver `terraform/README.md`).
2. Rodar `cd terraform && terraform init` (baixa providers/módulos — evita gastar os 80 minutos de aula com download).
3. Garantir que as imagens já foram publicadas pelo menos uma vez no GHCR (rodar o workflow de CI/CD manualmente — `workflow_dispatch` — ou já ter dado um push) para não depender da velocidade do build ao vivo.

---

## 3. Roteiro da aula (1h20 / 80 min)

A ideia central: **o Terraform sobe o EKS em background (12–18 min) enquanto
o instrutor explica arquitetura** — nada fica parado esperando.

| # | Min | Atividade | Pode rodar em paralelo? |
|---|---|---|---|
| 1 | 0–5 | Abertura: objetivo da aula, o ciclo AIOps (diagrama acima) | — |
| 2 | 5–8 | **Disparar `terraform apply -auto-approve` em um terminal separado** (fica rodando até o passo 7) | ✅ roda em background daqui até ~min 20 |
| 3 | 8–20 | Enquanto o EKS sobe: explicar o gotcha da `LabRole` no Terraform, mostrar `eks.tf`/`iam.tf` comentados, explicar as 3 apps e o mecanismo de chaos injection (`apps/README.md`) | paralelo ao passo 2 |
| 4 | 20–25 | Explicar o pipeline de CI/CD (Trivy + SonarCloud + GHCR) e mostrar uma execução já verde no GitHub Actions | paralelo ao passo 2, se ainda rodando |
| 5 | 25–28 | `terraform output kubeconfig_command` → `aws eks update-kubeconfig ...` → `kubectl get nodes` (confirmar 2 nós `AIOPS-workers` Ready) | depende do passo 2 ter terminado |
| 6 | 28–35 | Instalar ArgoCD + patch `--insecure` + Ingress ALB (`k8s/observability/README.md`, seção "Path A"). **Disparar a aplicação do `root-app-of-apps.yaml`** — ArgoCD assume a partir daqui e sincroniza tudo (observabilidade + apps + aiops-agent + postmortem) | ArgoCD sincroniza em background pelos próximos minutos |
| 7 | 35–40 | Enquanto ArgoCD sincroniza: criar os Secrets (`discord-webhook` em `monitoring`, `postmortem-secrets` em `aiops-lab` com `ANTHROPIC_API_KEY`+`DISCORD_WEBHOOK_URL`) e aplicar os ConfigMaps de dashboards/alertas do Grafana | paralelo à sincronização |
| 8 | 40–45 | Abrir a UI do ArgoCD (via ALB) e mostrar as Applications sincronizadas; abrir o Grafana (port-forward) e mostrar os 3 dashboards com tráfego chegando | — |
| 9 | 45–55 | **Demo ao vivo #1 — Observabilidade:** gerar carga leve nas 3 apps e mostrar métricas (Prometheus/Grafana), logs (Loki) e um trace (Tempo) do mesmo request, ponta a ponta | — |
| 10 | 55–65 | **Demo ao vivo #2 — Chaos + detecção + remediação:** `curl .../chaos/enable` (latência, depois http_errors, depois crash) em uma das apps → mostrar o Grafana alertando quase em tempo real → mostrar o `aiops-agent` remediando sozinho (`kubectl logs -f deploy/aiops-agent`, `kubectl get events -n aiops-lab --watch`, `GET /actions`) | — |
| 11 | 65–72 | **Demo ao vivo #3 — Postmortem automatizado:** mostrar a mensagem no Discord com o alerta e, em seguida, o PDF de RCA gerado pela Claude API chegando no mesmo canal | — |
| 12 | 72–77 | Fechamento: recapitular o ciclo completo, mostrar a tabela de extensões pós-aula (seção 7) | — |
| 13 | 77–80 | Perguntas + `terraform destroy -auto-approve` disparado ao final (fica rodando depois da aula encerrar) | roda em background no encerramento |

> **Dica de apresentação:** os passos 9, 10 e 11 são o "clímax" da aula — reserve
> um buffer de alguns minutos sobrando (o roteiro acima já tem folga nos
> passos 2–4 caso o Terraform demore mais que o esperado).

---

## 4. Passo a passo detalhado de deploy

### 4.1 Infraestrutura

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # ajuste se necessário
terraform init
terraform apply -auto-approve                  # ~15 min — deixe rodando em background

# depois que terminar:
aws eks update-kubeconfig --region us-east-1 --name aiops-lab-eks
kubectl get nodes -L node-group                # espere 2x "AIOPS"
```

Detalhes completos (inclusive o porquê de reaproveitar a `LabRole` do AWS
Academy em vez de criar IAM roles novas) em **`terraform/README.md`**.

### 4.2 CI/CD — publicar as imagens

As imagens usam exatamente estes nomes (já referenciados em todos os
manifests Kubernetes do repositório):

```
ghcr.io/cetertick/fiap-aiops-orders-api:latest
ghcr.io/cetertick/fiap-aiops-payments-api:latest
ghcr.io/cetertick/fiap-aiops-inventory-api:latest
ghcr.io/cetertick/fiap-aiops-aiops-agent:latest
ghcr.io/cetertick/fiap-aiops-postmortem-service:latest
```

Um push na branch `main` (ou `workflow_dispatch` manual) dispara
`.github/workflows/ci.yml`: Trivy (filesystem + imagem) → SonarCloud →
build → push para o GHCR. Configure o secret `SONAR_TOKEN` e marque o check
`ci-gate` como obrigatório em Settings → Branches para bloquear merges com
falhas críticas. Veja comentários no topo do workflow para o passo a passo
de habilitação.

### 4.3 ArgoCD + GitOps

```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# UI acessível via HTTP (simplificação para a aula) + ALB:
kubectl -n argocd patch configmap argocd-cmd-params-cm --type merge -p '{"data":{"server.insecure":"true"}}'
kubectl -n argocd rollout restart deployment argocd-server
kubectl apply -f k8s/argocd/argocd-ingress.yaml

# app-of-apps: sincroniza observabilidade + as 3 apps + aiops-agent + postmortem-service
kubectl apply -f k8s/argocd/root-app-of-apps.yaml
```

> A `targetRevision` do `root-app-of-apps.yaml` aponta para a branch de
> desenvolvimento `claude/confident-carson-hor10c`. Ao fazer merge para
> `main`, atualize esse campo (ver comentário no próprio arquivo).

### 4.4 Secrets (criar antes do Grafana/postmortem subirem, ou logo após)

```bash
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic discord-webhook -n monitoring \
  --from-literal=url=https://discord.com/api/webhooks/<id>/<token>

kubectl create namespace aiops-lab --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic postmortem-secrets -n aiops-lab \
  --from-literal=ANTHROPIC_API_KEY=<sua-chave> \
  --from-literal=DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/<id>/<token>
```

### 4.5 Dashboards e alertas do Grafana

```bash
kubectl apply -f k8s/observability/dashboards/ -f k8s/observability/alerting/
```

Detalhes (URLs/portas de cada componente, mecanismo de provisionamento de
alertas, troca de senha do Grafana) em **`k8s/observability/README.md`**.

### 4.6 Validar a stack de ponta a ponta

```bash
kubectl get applications -n argocd                 # todas "Synced"/"Healthy"
kubectl get pods -n aiops-lab -n monitoring -n argocd
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
# abrir http://localhost:3000 (usuário admin, senha: ver k8s/observability/README.md)
```

---

## 5. Roteiro da demo ao vivo (chaos → detecção → remediação → postmortem)

```bash
# 1) port-forward da orders-api (ou exponha via Service/ALB, se preferir)
kubectl -n aiops-lab port-forward svc/orders-api 8000:8000

# 2) injetar taxa de erro alta (gatilho do alerta HighErrorRate)
curl -X POST localhost:8000/chaos/enable \
  -H 'Content-Type: application/json' \
  -d '{"mode":"http_errors","intensity":70}'

# 3) acompanhar o aiops-agent detectando e remediando
kubectl -n aiops-lab logs -f deploy/aiops-agent
kubectl -n aiops-lab get events --watch
kubectl -n aiops-lab port-forward svc/aiops-agent 9100:9100 &
curl -s localhost:9100/actions | jq

# 4) no Grafana: ver o alerta "HighErrorRate" disparar (folder "AIOps Lab Alerts")
# 5) no Discord: mensagem do alerta chega quase junto; o PDF de postmortem
#    chega alguns segundos depois (gerado pela Claude API via postmortem-service)
```

Mais exemplos de chaos (latência, memory leak, crash) em **`apps/README.md`**.
Tabela de thresholds/ações do agente em **`aiops-agent/README.md`**.

---

## 6. Encerramento / limpeza

```bash
cd terraform
terraform destroy -auto-approve
```

Importante: como o state do Terraform é **local** (decisão deliberada, ver
`terraform/README.md` — contas do AWS Academy são efêmeras e não compensa
configurar um backend S3 para uma aula de 1h20), rode o `destroy` **na
mesma máquina/diretório** onde foi feito o `apply`, antes de encerrar a
sessão do Learner Lab.

---

## 7. Gaps conhecidos e extensões sugeridas (pós-aula)

Este laboratório prioriza ser **demonstrável em 1h20**, por isso faz
simplificações conscientes (documentadas nos READMEs de cada módulo). Para
evoluir o laboratório como atividade extra-classe ou projeto final:

| Gap / simplificação atual | Extensão sugerida |
|---|---|
| ALB expõe DNS, não IP fixo | Usar NLB + Elastic IP, ou Route53 + domínio próprio |
| Grafana sem Ingress público (só port-forward) | Adicionar Ingress ALB dedicado (mesmo padrão do ArgoCD) |
| Chaos injection manual via curl | Integrar **Chaos Mesh** ou **LitmusChaos** para cenários mais realistas e agendados |
| Detecção por threshold fixo (regras estáticas) | Detecção de anomalia com **ML** (ex. Prophet/STL para séries temporais, ou Amazon Lookout for Metrics) |
| Alertas só no Discord | Adicionar **Slack**, **PagerDuty**/**Opsgenie** para on-call real |
| Postmortem dispara 1x por alerta | Agrupar alertas correlacionados (mesmo incidente) antes de gerar o RCA |
| ArgoCD com `server.insecure=true` | TLS real via cert-manager + Let's Encrypt |
| Sem SLOs/error budget | Adicionar **Sloth** ou regras de SLO nativas do Prometheus/Grafana |
| Terraform com state local | Backend S3 + DynamoDB lock (fora do AWS Academy) |
| Observabilidade sem tracing completo end-to-end entre as 3 apps | Apps hoje não se chamam entre si — simular uma cadeia de chamadas (orders → payments → inventory) para traces distribuídos mais ricos |
| Sem políticas de custo | Adicionar **Kubecost** ou tags de custo + orçamento AWS Budgets |
| RBAC do aiops-agent é amplo dentro do namespace | Refinar com `resourceNames` específicos, auditoria via OPA/Kyverno |

---

## 8. Troubleshooting rápido

| Sintoma | Causa provável | Ação |
|---|---|---|
| `terraform apply` falha com `AccessDenied` em IAM | Tentando criar role nova no Academy | Confirme `use_lab_role = true` |
| Credenciais AWS expiram no meio da aula | Sessão do Learner Lab ~4h | Reexportar credenciais (painel "AWS Details") |
| Pods `ImagePullBackOff` | Imagem ainda não publicada no GHCR | Rodar o workflow de CI/CD (push ou `workflow_dispatch`) |
| Grafana não mostra métricas das apps | PodMonitor não detectado | Confirmar `podMonitorSelectorNilUsesHelmValues: false` aplicado e pods com label `app=<nome>` |
| Alerta do Grafana não chega no Discord | Secret `discord-webhook` ausente/errado, ou `$__env{}` não expandido nesta versão do chart | Ver fallback documentado em `k8s/observability/README.md` |
| `postmortem-service` não gera PDF | `ANTHROPIC_API_KEY` ausente ou inválida | Checar Secret `postmortem-secrets` em `aiops-lab` |
