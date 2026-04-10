FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

COPY . .

RUN chmod +x /app/resource/scripts/docker/*.sh \
    && mkdir -p /app/logs /app/resource/tmp_celery_logs /app/resource/tmp_celery_state /app/resource/logo_downloads

EXPOSE 8000

CMD ["gunicorn", "mango_project.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--threads", "8", "--timeout", "120"]
