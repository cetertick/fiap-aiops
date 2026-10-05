FROM python:3.12-slim

WORKDIR /app

# Dependências do sistema: nenhuma extra necessária (fpdf2 é puro Python,
# sem wkhtmltopdf/weasyprint), só certificados TLS para chamar Anthropic/Discord.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py observability.py llm.py pdf_render.py discord_notify.py main.py ./

# Usuário não-root
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
