FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY inferbench ./inferbench
RUN python -m pip install . \
    && mkdir -p /static/serve \
    && mkdir -p /data \
    && chown -R 10001:10001 /static /data

USER 10001:10001

EXPOSE 8080
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=2)"]

CMD ["inferbench", "--host", "0.0.0.0", "--port", "8080", "--data-dir", "/data"]
