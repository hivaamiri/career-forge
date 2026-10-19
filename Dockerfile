# Multi-stage/Slim Dockerfile for Job Pulse
FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install security certificates and required system packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user and directory hierarchy for persistent mounts
RUN useradd -u 1000 -m -s /bin/bash jobpulse && \
    mkdir -p /app/data /app/config /app/career-ops /app/scripts && \
    chown -R jobpulse:jobpulse /app

# Copy application code
COPY --chown=jobpulse:jobpulse main.py .
COPY --chown=jobpulse:jobpulse config/config.example.yaml config/
COPY --chown=jobpulse:jobpulse src/ src/
COPY --chown=jobpulse:jobpulse scripts/ scripts/

USER jobpulse

# Default command starts the orchestrator daemon loop
CMD ["python", "main.py"]
