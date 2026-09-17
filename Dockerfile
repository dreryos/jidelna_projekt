FROM python:3.14-slim

# Debian slim, ne Alpine. Důvod: psycopg, Pillow i WeasyPrint vydávají
# manylinux wheels, ne musllinux - na Alpine se všechno kompilovalo ze
# zdrojů (proto tam byl build-base). Vedlejší efekt: z produkce mizí
# release candidate Pythonu 3.15.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Systémové závislosti:
# - WeasyPrint: pango, cairo, gdk-pixbuf, shared-mime-info, fonty
# - postgresql-client: kvůli pg_dump pro zálohy. Major verze klienta musí
#   být >= major verze serveru, proto je držená shodně s postgres:17.
RUN apt-get update && apt-get install --no-install-recommends -y \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    shared-mime-info \
    fontconfig \
    fonts-dejavu \
    fonts-liberation \
    fonts-noto-core \
    postgresql-client-17 \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt && pip install gunicorn

# Copy project
COPY . /app/

# Datový adresář (zálohy databáze) a statika
RUN mkdir -p /app/data/backups /app/staticfiles

# Make entrypoint executable
RUN chmod +x /app/docker-entrypoint.sh

# Expose port
EXPOSE 8000

# Run entrypoint script
ENTRYPOINT ["/app/docker-entrypoint.sh"]
