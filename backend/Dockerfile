FROM python:3.11-slim

# Systémové závislosti (volitelné; ca-certificates pro HTTPS požadavky)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# requirements předem kvůli layer cachování
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# kód a data
COPY . /app/backend
# data mountujeme v docker-compose; vytvoříme jen adresář
RUN mkdir -p /app/data

# spouštěcí příkaz běží v docker-compose (uvicorn backend.app:app)
EXPOSE 8000
