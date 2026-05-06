FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple \
    PIP_TRUSTED_HOST=mirrors.cloud.tencent.com \
    PYTHONPATH=/app

WORKDIR /app

RUN sed -i \
        -e 's#http://deb.debian.org/debian#https://mirrors.cloud.tencent.com/debian#g' \
        -e 's#http://security.debian.org/debian-security#https://mirrors.cloud.tencent.com/debian-security#g' \
        /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources 2>/dev/null || true \
    && apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements-docker.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt

COPY apps/api /app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
