FROM python:3.12-slim AS base

WORKDIR /app

# Install dependencies first so code-only changes don't bust the layer cache.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py logutil.py promclient.py k8s_client.py metrics.py remediation.py state.py main.py ./

# Non-root user for the container.
RUN useradd --system --no-create-home --uid 10001 aiops
USER 10001

ENV PYTHONUNBUFFERED=1

EXPOSE 9100

CMD ["python", "main.py"]
