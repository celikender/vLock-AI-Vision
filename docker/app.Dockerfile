# vLock-AI Vision application: web UI, cameras, rules, Muse and SCADA outputs. No GPU.
# SAM runs in its own container (docker/sam.Dockerfile); the app waits for it (VLOCK_SAM_EXTERNAL=1).
FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 VLOCK_SAM_EXTERNAL=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY services services
COPY web web
COPY skills skills
RUN useradd --create-home --uid 1000 vlock && mkdir -p /data && chown vlock /data
USER vlock
# Same loopback-only address as a native start; host networking makes it reachable on this PC.
CMD ["python", "web/application.py", "--data-dir", "/data"]
