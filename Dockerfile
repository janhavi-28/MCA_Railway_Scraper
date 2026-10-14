FROM python:3.11-slim
# Build: v1.0.1-queue-worker-2026-10-14T18:35:00

# Force Python output to be completely unbuffered for live streaming Railway logs
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install minimal system utilities for networking and stability
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser dependencies (only Chromium)
RUN python -m playwright install --with-deps chromium || true

# Copy application source code
COPY master_main.py run_2026_enrichment.py stats_2026_enriched.py gdrive_sync.py proxies.txt* ./
COPY yearwise_csv/companies_2026.csv ./yearwise_csv/companies_2026.csv
COPY companies_2026_enriched.csv ./companies_2026_enriched.csv

# Default command: run batch enrichment using CONCURRENCY environment variable
CMD ["python", "-u", "run_2026_enrichment.py"]
