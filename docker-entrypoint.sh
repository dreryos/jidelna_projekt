#!/bin/sh

# Exit on error
set -e

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Creating superuser if needed..."
python create_superuser.py || true

echo "Starting Gunicorn..."
exec gunicorn --bind 0.0.0.0:8000 spiz_project.wsgi:application
