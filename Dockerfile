# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source
COPY src ./src
COPY scripts ./scripts
COPY README.md ./README.md

# Default environment
ENV PORT=5000
ENV HOST=0.0.0.0

EXPOSE 5000

CMD ["python", "src/web_app.py"]