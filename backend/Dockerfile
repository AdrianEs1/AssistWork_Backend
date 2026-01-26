# Etapa 1: build
FROM python:3.11-slim AS builder
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

# Al estar el Dockerfile en la misma carpeta que el txt:
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Etapa 2: imagen final
FROM python:3.11-slim
WORKDIR /app

# Copiar librerías
COPY --from=builder /install /usr/local

# Copiamos todo lo que hay en 'backend/' al WORKDIR (/app)
COPY . .

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Importante: Cloud Run setea PORT=8080 automáticamente
ENV PORT=8080

# AJUSTE CLAVE EN EL CMD:
# Como app.py está en la raíz del contenedor (/app/app.py), 
# ya no usas "backend.app:app", sino simplemente "app:app"
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port 8080"]

