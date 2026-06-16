#!/bin/bash

echo "Initial Django admin initialization."
cd /src

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Running migrations..."
python manage.py migrate --noinput

echo "Creating superuser and groups..."
python manage.py bootstrap

echo "Starting supervisord..."
exec "$@"
