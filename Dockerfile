FROM python:3.9-slim-bullseye

RUN apt-get update && apt-get install -y --no-install-recommends \
    wkhtmltopdf \
    xfonts-75dpi \
    xfonts-base \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -r appuser

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Dependencias de test dentro de la imagen: el contenedor corre como appuser y
# no puede instalarlas en tiempo de ejecución. Solo se añaden en desarrollo.
ARG INSTALL_DEV=false
COPY requirements-test.txt requirements-test.txt
RUN if [ "$INSTALL_DEV" = "true" ]; then \
        pip install --no-cache-dir -r requirements-test.txt; \
    fi

COPY . .

RUN mkdir -p /app/uploads && chown -R appuser:appuser /app
RUN chmod +x /app/entrypoint.sh /app/entrypoint.prod.sh /app/scripts/fix_migration_heads.sh

USER appuser

EXPOSE 5000

ENV FLASK_APP=run.py

CMD ["/app/entrypoint.prod.sh"]
