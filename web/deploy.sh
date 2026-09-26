#!/usr/bin/env bash
# Build and deploy the browser version to the fptp nginx host.
set -euo pipefail

cd "$(dirname "$0")/.."

host=${DEPLOY_HOST:-fptp}
domain=zangband.fromprompttoproduction.com
site=/etc/nginx/sites-available/zangband.conf
enabled=/etc/nginx/sites-enabled/zangband.conf
root=/var/www/zangband
cert=/etc/letsencrypt/live/$domain/fullchain.pem

web/build.sh
files="index.html zangband.js zangband.wasm zangband.data tiles sounds"
for file in index.html zangband.js zangband.wasm zangband.data \
        tiles/8x8.png tiles/16x16.png tiles/32x32.png tiles/nomad.png tiles/neon.png \
        sounds/sound.cfg; do
    test -s "web/dist/$file" || { echo "Missing web/dist/$file" >&2; exit 1; }
done

# Keep the current release in place until the complete upload is available.
stage=$(ssh "$host" 'sudo mktemp -d /var/www/zangband.stage.XXXXXXXX')
cleanup() {
    ssh "$host" "sudo rm -rf -- '$stage'" || true
}
trap cleanup EXIT
tar -C web/dist -cf - $files |
    ssh "$host" "sudo tar -C '$stage' -xf -"
ssh "$host" "sudo chmod -R a+rX '$stage'"

http_config() {
    cat <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $domain;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
        default_type text/plain;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}
EOF
}

https_config() {
    http_config
    cat <<EOF

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name $domain;

    ssl_certificate $cert;
    ssl_certificate_key /etc/letsencrypt/live/$domain/privkey.pem;

    root $root;
    index index.html;

    add_header Cache-Control "no-cache" always;
    add_header X-Content-Type-Options "nosniff" always;

    location / {
        try_files \$uri \$uri/ =404;
    }
}
EOF
}

install_config() {
    "$1" | ssh "$host" "sudo tee '$site' >/dev/null"
    ssh "$host" "sudo ln -sfn '$site' '$enabled' && sudo nginx -t && sudo systemctl reload nginx"
}

# The first run needs an HTTP virtual host for the ACME webroot challenge.
if ! ssh "$host" "sudo test -f '$cert'"; then
    install_config http_config
    ssh "$host" "sudo certbot certonly --webroot -w /var/www/letsencrypt -d '$domain' --non-interactive --agree-tos"
fi

install_config https_config

# Preserve the previous release until the staged directory is in place.
ssh "$host" "sudo rm -rf -- '$root.previous' && if sudo test -d '$root'; then sudo mv -- '$root' '$root.previous'; fi && if sudo mv -- '$stage' '$root'; then sudo rm -rf -- '$root.previous'; else sudo mv -- '$root.previous' '$root'; exit 1; fi"
trap - EXIT

echo "Deployed https://$domain/"
