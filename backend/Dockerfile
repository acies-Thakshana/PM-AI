FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data/samples ./data/samples
COPY data/raw ./data/raw
RUN mkdir -p data/sessions

# Run as a normal user, not root: the app only writes under data/ (local-mode sessions, logs, caches).
RUN useradd --system --uid 10001 --no-create-home appuser && chown -R appuser:appuser /app/data
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
