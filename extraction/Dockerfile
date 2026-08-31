# VPS-B extraction worker. LLM + GLiNER run on the GPU farm over HTTP, so this image needs no
# torch, no CUDA, no model weights -- just Python, a Postgres driver, an HTTP client, and psql for
# the one-shot schema migration. That keeps it small and fast to rebuild.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "psycopg[binary]>=3.1" "psycopg2-binary>=2.9" "httpx>=0.27"

WORKDIR /app
COPY . /app
RUN chmod +x /app/entrypoint.sh

ENV PYTHONUNBUFFERED=1
# Default role is the worker; compose overrides `command:` for feeder/cards/migrate.
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["worker"]
