FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Expose server ports: 4000 (TCP Health Server), 8000 (Prometheus Metrics), 8080 (WebSocket Gateway)
EXPOSE 4000 8000 8080

CMD ["python", "server/health_server.py"]
