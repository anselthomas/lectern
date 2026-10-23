#!/bin/bash
# Runs ON the app host (via `aws ssm send-command`): pull main, write env from SSM, rebuild and restart.
set -euo pipefail
REGION=ap-southeast-2
REPO=https://github.com/anselthomas/lectern.git
SRC=/opt/lectern/src

command -v git >/dev/null || dnf -y install git >/dev/null
if [ ! -d "$SRC/.git" ]; then git clone --depth 50 "$REPO" "$SRC"; fi
git -C "$SRC" fetch --depth 50 origin main
git -C "$SRC" reset --hard origin/main
echo "deploying $(git -C "$SRC" log -1 --format='%h %s')"

param() { aws ssm get-parameter --region "$REGION" --name "$1" --with-decryption --query Parameter.Value --output text; }
DBPW=$(param /lectern/db-password)
ORIGIN=$(param /lectern/origin-verify)
umask 077
cat > /opt/lectern/secrets.env <<EOF
POSTGRES_PASSWORD=$DBPW
DATABASE_URL=postgresql+psycopg://lectern:$DBPW@db:5432/lectern
ORIGIN_VERIFY=$ORIGIN
EOF
umask 022

mkdir -p /data/postgres /data/cache
chown 10001:10001 /data/cache
systemctl disable --now lectern-placeholder 2>/dev/null || true

cd "$SRC/deploy"
docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null
for i in $(seq 1 30); do
  if curl -fs -H "X-Origin-Verify: $ORIGIN" http://localhost/api/health >/dev/null; then echo "api healthy"; exit 0; fi
  sleep 2
done
echo "api did not become healthy"; docker compose logs --tail 80 api; exit 1
