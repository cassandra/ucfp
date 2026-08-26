#!/bin/bash

echo "Initial Django admin initialization."
cd /src

# One image serves both deployment lanes. The self-host lane bundles redis in
# this image; the cloud lane uses host redis. Enable the bundled-redis supervisor
# program only when asked, by copying it from the image's "available" staging dir
# into the active conf.d before supervisord reads it. Absence of the flag defaults
# to not bundling (the cloud lane).
if [ "${UCFP_BUNDLED_REDIS:-false}" = "true" ]; then
    echo "Enabling bundled redis..."
    cp /etc/supervisor/available/redis.conf /etc/supervisor/conf.d/redis.conf
else
    echo "Using external (host) redis; bundled redis disabled..."
    rm -f /etc/supervisor/conf.d/redis.conf
fi

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Running migrations..."
python manage.py migrate --noinput

echo "Creating superuser and groups..."
python manage.py bootstrap

echo "Seeding parameters..."
python manage.py seed_parameter_sets

echo "Seeding the example household..."
python manage.py seed_example_org

echo "Starting supervisord..."
exec "$@"
