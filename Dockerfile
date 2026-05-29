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

CMD ["python", "run.py"]




