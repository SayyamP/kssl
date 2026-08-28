"""Fetch the GLiNER weights into /models, once, before the first batch.

The image tries to bake them in at build time and is allowed to fail at it (see
the Dockerfile). This is the recovery: run it once per machine, with the models
volume mounted, and every later run starts cold-start-safe.

    docker compose -f docker-compose.extract.yml run --rm extract python /usr/local/bin/warm.py
"""
import os
import sys
import time

MODEL = os.environ.get("C_GLINER", "urchade/gliner_multi-v2.1")

print("HF_HOME=%s" % os.environ.get("HF_HOME", "(unset)"))
print("fetching %s ..." % MODEL)

for attempt in range(1, 4):
    try:
        from gliner import GLiNER
        t0 = time.time()
        GLiNER.from_pretrained(MODEL)
        print("ok in %.0fs -- weights are in %s and persist with the volume"
              % (time.time() - t0, os.environ.get("HF_HOME", "?")))
        sys.exit(0)
    except Exception as exc:                            # noqa: BLE001
        print("attempt %d failed: %s" % (attempt, str(exc)[:200]))
        if attempt < 3:
            time.sleep(10)

sys.exit("could not fetch the weights. Check that the container can resolve "
         "huggingface.co, and that the box has a route to it (this host "
         "resolves it to IPv6 only -- an IPv4-only route will fail).")
