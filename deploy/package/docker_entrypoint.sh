#!/bin/bash

echo "Initial Django admin initialization."
cd /src

# One image serves both deployment lanes. The self-host lane bundles redis in
# this image; the cloud lane uses host redis. Enable the bundled-redis supervisor
# program only when asked, by copying it from the image's "available" staging dir
# into the active conf.d before supervisord reads it.
if [ "${UCFP_BUNDLED_REDIS:-false}" = "true" ]; then
    echo "Enabling bundled redis..."
    cp /etc/supervisor/available/redis.conf /etc/supervisor/conf.d/redis.conf
else
    echo "Using external (host) redis; bundled redis disabled..."
    rm -f /etc/supervisor/conf.d/redis.conf
fi

# The container's nginx listens on DJANGO_SERVER_PORT (default 8000). Templating it
# here -- rather than baking a fixed port into docker_nginx.conf -- lets several
# app containers share one host under `network_mode: host` by each taking a
# distinct port. The config file ships with :8000 so it stays valid for the
# build-time `nginx -t`; this rewrites the listen directives before nginx starts.
APP_PORT="${DJANGO_SERVER_PORT:-8000}"
if ! [[ "${APP_PORT}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: DJANGO_SERVER_PORT='${APP_PORT}' is not a positive integer." >&2
    exit 1
fi
echo "Configuring nginx to listen on port ${APP_PORT}..."
sed -i -E "s/(listen[[:space:]]+[^;]+):[0-9]+;/\1:${APP_PORT};/" \
    /etc/nginx/sites-available/default

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
