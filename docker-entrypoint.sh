#!/bin/sh

# Exit on error
set -e

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Building help documentation (MkDocs)..."
mkdocs build

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Creating superuser if needed..."
python create_superuser.py || true

echo "Purging expired receipt scans..."
python manage.py purge_receipt_scans || true

echo "Starting Gunicorn..."
# --max-requests: WeasyPrint (Pango) nechává po každém PDF trochu paměti
# navíc, takže se worker po 200 requestech recykluje. Jitter rozhodí
# recyklaci v čase, ať se všichni workeři neobnovují naráz.
exec gunicorn --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 120 \
    --graceful-timeout 30 \
    --max-requests 200 \
    --max-requests-jitter 50 \
    --log-level info \
    spiz_project.wsgi:application
