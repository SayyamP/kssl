# The LLM / GLiNER API. Runs on VPS-B, beside the Ollama it fronts.
#
# No torch, no gliner, no model weights: this process forwards calls, it does not run
# models. That is what keeps it a ~60 MB image on a box whose cores are the constraint.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt /srv/llmapi/requirements.txt
RUN pip install --no-cache-dir -r /srv/llmapi/requirements.txt

COPY . /srv/llmapi/
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/srv

# Bound to loopback by default. The API answers to the pipeline on this host, and there is
# no reason for it to be reachable from the network -- it holds the farm's Bearer key.
CMD ["sh", "-c", "exec uvicorn llmapi.server:app --host ${LLMAPI_BIND:-127.0.0.1} --port ${LLMAPI_PORT:-8610}"]
