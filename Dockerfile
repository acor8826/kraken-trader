# =============================================================================
# Crypto Trading Agent - Production Dockerfile
# =============================================================================
#
# Multi-stage build for optimized production image
#
# Build: docker build -t crypto-trader:latest .
# Run:   docker run -d -p 8080:8080 --env-file .env crypto-trader:latest
#
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Builder
# -----------------------------------------------------------------------------
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# -----------------------------------------------------------------------------
# Stage 2: Production
# -----------------------------------------------------------------------------
FROM python:3.11-slim as production

# Labels
LABEL maintainer="Crypto Trader Team"
LABEL version="3.0.0"
LABEL description="Claude-powered autonomous cryptocurrency trading agent"

# Security: Create non-root user
RUN groupadd -r trader && useradd -r -g trader trader

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY . .

# Create necessary directories and set ownership
RUN mkdir -p /app/output /app/logs /app/data/cache /tmp/prometheus && \
    chown -R trader:trader /app /tmp/prometheus

# Environment configuration
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8080
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus

# Switch to non-root user
USER trader

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run application
CMD ["python", "main.py"]
