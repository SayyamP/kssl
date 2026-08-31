# GLiNER as a service, one per node. Replaces the in-process torch model that used to
# live inside every extraction worker.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# CPU torch FIRST and from its own index. A plain `pip install torch` pulls the CUDA
# build -- ~2 GB that cannot be used on any box in this fleet.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch

COPY requirements.txt /srv/req.txt
RUN pip install --no-cache-dir -r /srv/req.txt

WORKDIR /srv
COPY . /srv/llmapi/gliner_server/
RUN touch /srv/llmapi/__init__.py

# Weights land here on first use; a named volume keeps them across restarts so a redeploy
# is not a fresh download on every node.
ENV HF_HOME=/models PYTHONUNBUFFERED=1 PYTHONPATH=/srv

# The model loads at STARTUP, not on the first request: a lazy load makes the first caller
# pay ~30s inside its own timeout, and the router records that as a slow node rather than
# a cold one. start_period on the healthcheck covers the load.
CMD ["sh", "-c", "exec uvicorn llmapi.gliner_server.app:app --host ${GLINER_BIND:-0.0.0.0} --port ${GLINER_PORT:-8620}"]
