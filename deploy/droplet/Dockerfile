# Pin specific Python version for consistency across platforms
FROM python:3.11.8-bookworm

# Install dependencies with curl for healthcheck. The droplet image does NOT
# bundle redis (it uses external/host redis) but keeps redis-tools for the
# redis readiness check in docker-start-gunicorn.sh, plus the MySQL client
# build deps that mysqlclient needs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        supervisor \
        nginx \
        redis-tools \
        default-libmysqlclient-dev \
        pkg-config \
        build-essential \
    && mkdir -p /var/log/supervisor \
    && mkdir -p /etc/supervisor/conf.d \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip

WORKDIR /src

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/src

EXPOSE 8000

VOLUME /data/database /data/media
RUN mkdir -p /data/database && mkdir -p /data/media

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Installs requirements/production.txt (which is `-r base.txt` by default).
# mysqlclient is NOT a default dependency -- the droplet/MySQL adaptation adds it
# to base.txt (see docs/dev/project/droplet-deployment.md); the MySQL
# apt build deps above are pre-included so that step builds with no edits here.
# base.txt is copied alongside so the `-r base.txt` include resolves.
COPY src/ucfp/requirements/base.txt /src/base.txt
COPY src/ucfp/requirements/production.txt /src/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt

COPY deploy/droplet/docker_supervisord.conf /etc/supervisor/conf.d/ucfp.conf
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
