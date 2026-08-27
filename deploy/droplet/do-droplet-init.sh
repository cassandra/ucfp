#!/bin/bash
#
# RETIRED -- host provisioning moved to the shared `droplet-ops` repo.
#
# A droplet may host several apps side by side sharing one host MySQL, redis,
# Docker, and nginx. That singleton host state -- and each app's DB/user, nginx
# vhost, TLS cert, and port/redis-index assignment -- is now owned by `droplet-ops`
# so app repos no longer each carry a conflicting copy of "provision the host".
#
# Use, from a clone of droplet-ops on the droplet:
#   ./provision-host.sh                                  # fresh droplet, once
#   ./add-app.sh ucfp <domain> <port> <redis-index> [email]   # register ucfp
#
# See docs/dev/project/droplet-setup.md (step 3).

echo "do-droplet-init.sh is retired -- provisioning now lives in the droplet-ops repo." >&2
echo "Run provision-host.sh (once per host) then add-app.sh for ucfp; see" >&2
echo "docs/dev/project/droplet-setup.md step 3." >&2
exit 1
