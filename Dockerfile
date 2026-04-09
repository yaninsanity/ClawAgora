FROM python:3.13-slim

ARG GIT_SHA=
ENV GIT_SHA=${GIT_SHA}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src:/app/apps/server \
    DJANGO_SETTINGS_MODULE=clawagora_server.settings

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY apps/server /app/apps/server
COPY examples /app/examples
COPY scripts /app/scripts

RUN pip install --upgrade pip \
    && pip install -e ".[server,async]"

EXPOSE 8000

CMD ["bash", "scripts/dev.sh"]
