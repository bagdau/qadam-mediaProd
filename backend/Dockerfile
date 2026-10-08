# syntax=docker/dockerfile:1.7
# ---------- builder: resolve and compile wheels once ----------
FROM python:3.13-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# ---------- runtime: no compilers, no pip cache, non-root ----------
FROM python:3.13-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    PATH="/home/app/.local/bin:$PATH" MEDIA_DIR=/data/media
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /home/app --create-home --shell /usr/sbin/nologin app \
 && mkdir -p /data/media /var/run/beat && chown -R app:app /data /var/run/beat
WORKDIR /app
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt && rm -rf /wheels
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app
COPY --chown=app:app devtools ./devtools
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).status == 200 else 1)"
# Behind nginx on a private network only: trust its X-Forwarded-* headers.
# --no-access-log: uvicorn would log query strings (OAuth `code`/`state`); the app logs paths only.
CMD ["uvicorn", "app.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "30", \
     "--no-server-header", "--no-access-log"]
