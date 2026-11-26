FROM python:3.11-slim

# Non-root user
RUN groupadd -r app && useradd -r -g app app

WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e "." && pip install --no-cache-dir uvicorn[standard]

# Copy source
COPY src/ ./src/

# Static assets
COPY src/companylens/api/static/ ./src/companylens/api/static/

RUN chown -R app:app /app
USER app

ENV OMP_NUM_THREADS=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "src.companylens.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
