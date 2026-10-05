"""
Configuração centralizada do serviço, lida a partir de variáveis de ambiente.

Mantemos tudo aqui para facilitar os testes e deixar claro quais variáveis
precisam estar presentes no Deployment/Secret do Kubernetes.
"""
import os

# --- Anthropic ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")

# --- Discord ---
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
DISCORD_MAX_FILE_BYTES = 8 * 1024 * 1024  # limite padrão de webhooks do Discord (8MB)

# --- Observabilidade ---
PROMETHEUS_URL = os.environ.get(
    "PROMETHEUS_URL",
    "http://kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090",
)
LOKI_URL = os.environ.get(
    "LOKI_URL",
    "http://loki.monitoring.svc.cluster.local:3100",
)
NAMESPACE = os.environ.get("APP_NAMESPACE", "aiops-lab")

# Janela de tempo (em minutos) usada para buscar métricas/logs recentes.
CONTEXT_WINDOW_MINUTES = int(os.environ.get("CONTEXT_WINDOW_MINUTES", "10"))

# Timeouts defensivos para chamadas HTTP de observabilidade (não devem travar o webhook).
HTTP_TIMEOUT_SECONDS = float(os.environ.get("OBS_HTTP_TIMEOUT_SECONDS", "5"))

PLACEHOLDER_UNAVAILABLE = "dados indisponíveis"
