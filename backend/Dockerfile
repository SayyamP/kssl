FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app.py .
# The stage timer is shared with the pipeline rather than duplicated here: two
# copies of the code that decides what a timing means is how the two halves of
# a metric drift apart. The build context is the repo root so this is reachable.
COPY pipeline/stage_timer.py ./pipeline/stage_timer.py
# the article-bench page, served at /api/bench
COPY bench/dashboard.html ./bench/dashboard.html
EXPOSE 8600
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8600"]
