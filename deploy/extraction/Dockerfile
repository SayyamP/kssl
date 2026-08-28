# Layer A/B extraction, CPU only, for the data centre.
#
# Two things this gets right that the older l2/comprehend/deploy/Dockerfile did
# not:
#
#   * gliner and transformers are PINNED. gliner 0.2.13 requires
#     transformers<4.46, and the engine's own check.py fails the run on a
#     version mismatch -- an unpinned install produces a container that builds
#     fine and refuses to work.
#   * torch comes from the CPU index. The data centre has no GPU (measured and
#     settled), and the default wheel drags in ~2 GB of CUDA that could never be
#     used. The warnings elsewhere in this repo that a CPU wheel "costs 30x on
#     every GLiNER pass" are wrong: gliner's from_pretrained defaults to
#     map_location="cpu" and never selects a device, so GLiNER runs on CPU even
#     on the GPU workstation. Nothing is lost by moving it.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models \
    C_GLINER=urchade/gliner_multi-v2.1 \
    C_GLINER_TH=0.2 \
    C_MODEL=qwen2.5:7b \
    C_EMBED=nomic-embed-text:latest

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# torch first and alone, so pip cannot resolve a CUDA build in from a
# transitive requirement
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

RUN pip install \
      "gliner==0.2.13" \
      "transformers==4.45.2" \
      "httpx>=0.27" \
      "numpy>=1.26" \
      "psycopg2-binary" \
      "pyyaml"

# Try to bake the GLiNER weights in, but do NOT fail the build on it.
# Measured on this data centre: the host and a running container both resolve
# huggingface.co fine, while BuildKit's network namespace does not -- so a
# hard dependency here makes the image unbuildable for a reason that has
# nothing to do with the image. If this step is skipped, `warm.py` fetches the
# weights at first run into the mounted /models volume, where they persist.
RUN python -c "from gliner import GLiNER; GLiNER.from_pretrained('urchade/gliner_multi-v2.1')"     || echo "weights not baked -- run warm.py once before the first batch"

COPY warm.py /usr/local/bin/warm.py

WORKDIR /app
CMD ["python", "-c", "print('extraction image ready; mount the engine and run run_extraction.py')"]
