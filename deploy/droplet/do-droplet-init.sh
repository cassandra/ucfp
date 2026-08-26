#!/bin/bash
#
# One-time provisioning for a fresh production droplet (Ubuntu/Debian).
# Installs Docker, an nginx + certbot TLS reverse proxy, MySQL, Redis, and
# docker-compose, then prepares /opt/ucfp to receive deployments.
#
# Usage (run on the droplet):
#   ./do-droplet-init.sh <domain> [admin-email]
# e.g.
#   ./do-droplet-init.sh app.example.com admin@example.com

set -e

DOMAIN="${1:?Usage: $0 <domain> [admin-email]}"
ADMIN_EMAIL="${2:-admin@$DOMAIN}"
DOCKER_APP_PORT=8000

echo "Updating system ..."
apt update && apt upgrade -y

echo "Installing Docker ..."
apt install -y docker.io
systemctl enable docker
sudo systemctl start docker

echo "Installing Nginx + Certbot ..."
apt install -y nginx certbot python3-certbot-nginx
systemctl enable nginx
sudo systemctl start nginx

echo "Configuring Nginx reverse proxy ..."

# Suppress existing default config to avoid port conflict
rm -f /etc/nginx/sites-enabled/default

# HTTP-only on purpose. `certbot --nginx` (run below, after DNS) obtains the
# certificate AND injects the `listen 443 ssl` server block plus the 80->443
# redirect itself -- so we never reference cert files that do not exist yet
# (which would make `nginx -t` fail on a fresh host before certbot can run).
cat > /etc/nginx/sites-available/ucfp <<EOF
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;

    location / {
        proxy_pass http://localhost:$DOCKER_APP_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

ln -s /etc/nginx/sites-available/ucfp /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

echo "Installing MySQL ..."
sudo apt install -y mysql-server
sudo systemctl enable mysql
sudo systemctl start mysql

echo "Installing Redis ..."
sudo apt install -y redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server

echo "Installing docker-compose ..."
sudo apt install -y docker-compose

echo "Creating deployment directory ..."
mkdir -p /opt/ucfp

# After DNS points at this server, obtain the certificate. `certbot --nginx`
# adds the HTTPS (listen 443 ssl) server block and the 80->443 redirect to the
# nginx config above.
echo "*********"
echo "* NOTICE: Run certbot after DNS points here to enable HTTPS."
echo "* "
echo "*         certbot --nginx -d $DOMAIN -d www.$DOMAIN --non-interactive --agree-tos -m $ADMIN_EMAIL"
echo "* "
echo "* Renewal is automatic: the certbot package installs a systemd timer"
echo "* (certbot.timer) that renews the cert and reloads nginx before expiry."
echo "*********"
echo "* NOTICE: the release deploy step pulls the app image from GitHub Container Registry"
echo "*         (ghcr.io/cassandra/ucfp). If that package is private, authenticate"
echo "*         this droplet to GHCR once:"
echo "* "
echo "*         echo <GITHUB_PAT> | docker login ghcr.io -u <github-username> --password-stdin"
echo "* "
echo "*         A public package needs no login."
echo "*********"

echo "Ready."
