FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app.py .
# The stage timer is shared with the pipeline rather than duplicated here: two
# copies of the code that decides what a timing means is how the two halves of
# a metric drift apart. The build context is the repo root so this is reachable.
COPY pipeline/stage_timer.py ./pipeline/stage_timer.py
# The threat/severity grade, for the same reason: one definition, shared with the
# pipeline that writes the cards. aliases.py comes with it -- threat_gate resolves a
# card's company through the repo's identity layer rather than growing a second one.
COPY extraction/signals/threat_gate.py ./threat_gate.py
COPY extraction/signals/aliases.py ./aliases.py
# the article-bench page, served at /api/bench
COPY bench/dashboard.html ./bench/dashboard.html
EXPOSE 8600
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8600"]
