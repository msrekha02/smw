FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY api ./api
COPY worker ./worker
COPY providers ./providers
COPY scripts ./scripts
COPY db ./db
COPY fixtures ./fixtures
COPY tests ./tests
COPY pytest.ini docker-entrypoint-worker.sh ./
RUN chmod +x /app/docker-entrypoint-worker.sh

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
