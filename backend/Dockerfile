FROM python:3.11-slim

# ========= Systémové závislosti =========
# - ca-certificates, curl: HTTPS / ladění
# - poppler-utils: pdf2image (PDF -> obrázky)
# - tesseract-ocr (+ lang balíčky): OCR
# - libjpeg/libpng/libx*: Pillow / pdf2image runtime
# - unixodbc(+dev): ODBC runtime pro pyodbc
# - msodbcsql18: Microsoft ODBC Driver 18 for SQL Server
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    poppler-utils \
    libjpeg62-turbo \
    libpng16-16 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libglib2.0-0 \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-deu \
    tesseract-ocr-ces \
    unixodbc \
    unixodbc-dev \
    apt-transport-https \
    gnupg \
 && curl https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /usr/share/keyrings/microsoft-prod.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/microsoft-prod.list \
 && apt-get update \
 && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
 && rm -rf /var/lib/apt/lists/*

# ========= Pracovní adresář =========
WORKDIR /app

# ========= Python závislosti =========
# POZN.: Ujisti se, že v requirements.txt máš i `pyodbc==5.1.0`
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# ========= Kód a data =========
# Backend kód (app, API, RAG, atd.)
COPY . /app/backend

# Předpřipravíme datovou složku
RUN mkdir -p /app/data

# ========= Prostředí =========
# Absolutní importy typu "from backend.xxx import ..."
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

# ========= Síť a spuštění =========
EXPOSE 8000
# Spouštěcí příkaz definuje docker-compose (uvicorn backend.app:app)
