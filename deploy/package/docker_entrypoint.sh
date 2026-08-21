#!/bin/bash

echo "Initial Django admin initialization."
cd /src

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Running migrations..."
python manage.py migrate --noinput

echo "Creating superuser and groups..."
python manage.py bootstrap

echo "Seeding parameters..."
python manage.py seed_parameter_sets

echo "Seeding the sample household..."
python manage.py seed_sample_org

echo "Starting supervisord..."
exec "$@"
