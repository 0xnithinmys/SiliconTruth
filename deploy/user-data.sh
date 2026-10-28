#!/bin/bash
# Boots the SiliconTruth host: Docker, the app container, and nginx in front.
#
# Secrets are read from SSM Parameter Store at container start, never baked
# into the image or the launch template. The instance role grants GetParameter
# on /silicontruth/* only.
set -euxo pipefail

dnf -y update
dnf -y install docker nginx
systemctl enable --now docker

REGION=us-east-1
ACCOUNT=323708468700
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

# The deploy script, re-run by CI on every push.
cat > /usr/local/bin/silicontruth-deploy <<'DEPLOY'
#!/bin/bash
set -euo pipefail
REGION=us-east-1
ACCOUNT=323708468700
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
TAG="${1:-latest}"

aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

docker pull "$REGISTRY/silicontruth-app:$TAG"
# The oracle image the emulate gate starts. Pulled here so the first live run
# does not pay for a 1 GB download while someone waits.
docker pull "$REGISTRY/silicontruth-oracle:1.15.3" || true
docker tag "$REGISTRY/silicontruth-oracle:1.15.3" silicontruth-oracle:1.15.3 || true

get() { aws ssm get-parameter --region "$REGION" --name "$1" --with-decryption \
          --query Parameter.Value --output text 2>/dev/null || true; }
MODEL_API_KEY="$(get /silicontruth/MODEL_API_KEY)"
LIVE_PASSWORD="$(get /silicontruth/LIVE_PASSWORD)"

docker rm -f silicontruth >/dev/null 2>&1 || true
docker run -d --name silicontruth --restart unless-stopped \
  -p 127.0.0.1:3000:3000 \
  -e NODE_ENV=production \
  -e MODEL_API_KEY="$MODEL_API_KEY" \
  -e LIVE_PASSWORD="$LIVE_PASSWORD" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  "$REGISTRY/silicontruth-app:$TAG"

docker image prune -f >/dev/null 2>&1 || true
DEPLOY
chmod +x /usr/local/bin/silicontruth-deploy

# nginx terminates :80 and proxies to the container on loopback, so the app
# port is never exposed directly.
cat > /etc/nginx/conf.d/silicontruth.conf <<'NGINX'
server {
    listen 80 default_server;
    server_name _;
    # A reference manual is tens of MB and the upload is the whole point.
    client_max_body_size 80m;
    # A live run takes minutes: extraction, codegen, then an emulator.
    proxy_read_timeout 900s;
    proxy_send_timeout 900s;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # Basic auth is checked by the app, so the header must survive.
        proxy_set_header Authorization $http_authorization;
    }
}
NGINX
rm -f /etc/nginx/conf.d/default.conf || true
systemctl enable --now nginx
nginx -t && systemctl reload nginx

/usr/local/bin/silicontruth-deploy latest || true
