FROM python:3.12-slim

WORKDIR /app

# Dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    smbclient \
    cifs-utils \
    && rm -rf /var/lib/apt/lists/*

# Dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código fuente
COPY . .

# Directorio de logs
RUN mkdir -p /app/logs

EXPOSE 8000

# Sin --reload: es una bandera de desarrollo. Con el bind mount de
# docker-compose (./backend:/app), cualquier escritura de un .py reinicia el
# proceso y mata las peticiones en vuelo — incluida la sincronización con
# Trazalo, que corre en un hilo de fondo y perdería su estado a mitad.
# Para desarrollo local, sobrescribir el comando en docker-compose.override.yml.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
