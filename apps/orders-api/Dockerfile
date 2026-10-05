# orders-api - multi-stage build, small final image, non-root user
FROM python:3.12-slim AS build

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser

COPY --from=build /install /usr/local
WORKDIR /app
COPY main.py .

USER appuser

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
