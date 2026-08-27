# Pin specific Python version for consistency across platforms
FROM python:3.11.8-bookworm

# One image serves both deployment lanes. It always carries redis-server (started
# by supervisord only in the self-host lane -- see the entrypoint's
# UCFP_BUNDLED_REDIS handling) and the MySQL client + build deps that mysqlclient
# needs (exercised only when the cloud lane selects the MySQL backend). curl is
# for the healthcheck; redis-tools provides the readiness check in
# docker-start-gunicorn.sh.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        supervisor \
        nginx \
        redis-server \
        redis-tools \
        default-libmysqlclient-dev \
        pkg-config \
        build-essential \
    && mkdir -p /var/log/supervisor \
    && mkdir -p /etc/supervisor/conf.d \
    && mkdir -p /etc/supervisor/available \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip

WORKDIR /src

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/src

# Documentation only; the effective port is DJANGO_SERVER_PORT (default 8000),
# which the entrypoint templates into nginx and the healthcheck reads below.
EXPOSE 8000

VOLUME /data/database /data/media
RUN mkdir -p /data/database && mkdir -p /data/media

# Shell-form so DJANGO_SERVER_PORT (from the env file) is resolved at check time,
# matching the port the entrypoint configured nginx to listen on.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${DJANGO_SERVER_PORT:-8000}/health || exit 1

# base.txt is the full production dependency set (production.txt is just an alias
# for it); dev-only tooling is intentionally excluded.
COPY src/ucfp/requirements/base.txt /src/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt

# Always-on programs (gunicorn + nginx) go straight into conf.d. The bundled-redis
# program ships to an "available" staging dir and is enabled into conf.d by the
# entrypoint only when UCFP_BUNDLED_REDIS is true (the self-host lane).
COPY deploy/package/docker_supervisord.conf /etc/supervisor/conf.d/ucfp.conf
COPY deploy/package/docker_supervisord_redis.conf /etc/supervisor/available/redis.conf
COPY deploy/package/docker_nginx.conf /etc/nginx/sites-available/default

# Clean up nginx default configurations and ensure proper symlinks
RUN rm -f /etc/nginx/conf.d/default.conf \
    && rm -f /etc/nginx/sites-enabled/default \
    && ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default \
    && nginx -t

COPY deploy/package/docker_entrypoint.sh /src/entrypoint.sh
RUN chmod +x /src/entrypoint.sh

COPY VERSION /VERSION
COPY src /src
RUN chmod +x /src/bin/docker-start-gunicorn.sh

ENTRYPOINT ["/src/entrypoint.sh"]

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf" ]
