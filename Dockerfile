FROM python:3.9-slim-bookworm

# Debian 11 LTS ended 2026-08-31. The bullseye-security CDN started 404'ing
# packages that wkhtmltopdf/ffmpeg pull in (qt, mesa, libaom, libswscale),
# so the image build died on apt-get install. Bookworm still ships curl and
# ffmpeg; Debian 12 dropped wkhtmltopdf, so we pin the last official .deb.
ARG TARGETARCH
ARG WKHTMLTOX_VERSION=0.12.6.1-3

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        fontconfig \
        fonts-dejavu-core \
        libjpeg62-turbo \
        libx11-6 \
        libxcb1 \
        libxext6 \
        libxrender1 \
        xfonts-75dpi \
        xfonts-base \
    ; \
    case "${TARGETARCH:-amd64}" in \
      amd64) wkarch=amd64 ;; \
      arm64) wkarch=arm64 ;; \
      *) echo "arquitectura no soportada para wkhtmltopdf: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL --retry 5 --retry-delay 2 -o /tmp/wkhtmltox.deb \
      "https://github.com/wkhtmltopdf/packaging/releases/download/${WKHTMLTOX_VERSION}/wkhtmltox_${WKHTMLTOX_VERSION}.bookworm_${wkarch}.deb"; \
    apt-get install -y --no-install-recommends /tmp/wkhtmltox.deb; \
    rm -f /tmp/wkhtmltox.deb; \
    rm -rf /var/lib/apt/lists/*; \
    wkhtmltopdf --version; \
    command -v ffmpeg

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

# Procesar logos en build (host de deploy suele no tener Pillow/pip).
RUN bash scripts/sync_brand_assets.sh

RUN mkdir -p /app/uploads && chown -R appuser:appuser /app
RUN chmod +x /app/entrypoint.sh /app/entrypoint.prod.sh /app/scripts/fix_migration_heads.sh /app/scripts/sync_brand_assets.sh

USER appuser

EXPOSE 5000

ENV FLASK_APP=run.py

CMD ["/app/entrypoint.prod.sh"]
