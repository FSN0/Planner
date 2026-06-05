FROM python:3.9-slim-bullseye
# Instala dependencias y wkhtmltopdf
RUN apt-get update && apt-get install -y \
    wkhtmltopdf \
    xfonts-75dpi \
    xfonts-base

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/uploads

EXPOSE 5000

# Servidor de producción (NO usar el servidor de desarrollo de Flask).
# Ajusta el número de workers según los núcleos del servidor.
CMD ["gunicorn", "--workers", "4", "--timeout", "120", "--bind", "0.0.0.0:5000", "run:app"]




