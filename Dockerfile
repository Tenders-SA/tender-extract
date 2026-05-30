# Tender Extract API
# Multi-stage build optimized for Cloud Run
# Addresses cold start and memory issues

# ============= BUILD STAGE =============
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ============= RUNTIME STAGE =============
FROM python:3.12-slim-bookworm

WORKDIR /app

# Install runtime system packages for legacy document format support
RUN apt-get update && apt-get install -y --no-install-recommends \
    antiword \
    catdoc \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Cloud Run environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    GUNICORN_WORKERS=2 \
    GUNICORN_TIMEOUT=120 \
    LOG_LEVEL=info

# Copy application code
COPY app/ ./app/
COPY gunicorn.conf.py ./

# Expose port (informational)
EXPOSE 8080

# Use gunicorn with custom config
CMD ["gunicorn", "app.main:app", "-c", "gunicorn.conf.py"]
