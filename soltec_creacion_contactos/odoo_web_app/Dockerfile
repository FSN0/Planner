FROM python:3.10-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Usamos Gunicorn para producción, exponiendo el puerto 5000
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5002", "app:app"]