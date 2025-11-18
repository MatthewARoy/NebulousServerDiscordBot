# Multi-stage build for optimized container size
FROM python:3.11-slim as builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create and set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=nebulous_project.settings

# Create non-root user for security
RUN useradd -m -u 1000 botuser && \
    mkdir -p /app /app/staticfiles && \
    chown -R botuser:botuser /app

# Set working directory
WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=botuser:botuser . .

# Make startup script executable (before switching to non-root user)
RUN chmod +x /app/start-server.sh

# Switch to non-root user
USER botuser

# Collect static files
RUN python manage.py collectstatic --noinput || true

# Expose port for health check endpoint
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/').read()" || exit 1

# Default command - run startup script
# This starts both web server (for health checks) and bot
CMD ["./start-server.sh"]

