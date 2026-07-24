FROM python:3.11-slim

# System deps: ffmpeg (pydub/M4B export) and tini (proper PID 1 / signal handling)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tini curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x entrypoint.sh

# Persisted data lives under /data, not baked into the image layer, so a
# container replacement does not erase cache/outputs when mounted as a volume.
ENV UPLOAD_FOLDER=/data/uploads \
    OUTPUT_FOLDER=/data/outputs \
    CACHE_FOLDER=/data/cache \
    PORT=5000 \
    HOST=0.0.0.0 \
    ROLE=api

# Non-root user (blueprint: "drop container root").
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/uploads /data/outputs /data/cache \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:5000/api/health || exit 1

# tini as init for signal handling. The entrypoint runs migrations (api role)
# then execs the given command. Override CMD in the worker service.
ENTRYPOINT ["tini", "--", "./entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "3600", "wsgi:app"]
