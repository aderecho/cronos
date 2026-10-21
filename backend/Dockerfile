FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends default-libmysqlclient-dev build-essential pkg-config && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ /app/
COPY agent/ /opt/cronos-agent-downloads/
ENV CRONOS_AGENT_SOURCE_DIR=/opt/cronos-agent-downloads
RUN useradd --system --uid 10001 cronos && chown -R cronos:cronos /app
USER cronos
EXPOSE 8100
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8100", "--workers", "3", "--ws-max-size", "4096"]
