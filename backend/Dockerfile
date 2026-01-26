# Etapa 1: build
FROM python:3.11-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Etapa 2: imagen final
FROM python:3.11-slim
WORKDIR /app

# Copiar librerías
COPY --from=builder /install /usr/local

# Configurar cache de HuggingFace
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface

# DESCARGAR EL MODELO DE EMBEDDINGS ANTES DE COPIAR EL CÓDIGO
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# Ahora copiamos el código
COPY . .

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Usar variable de entorno PORT que Cloud Run setea dinámicamente
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
