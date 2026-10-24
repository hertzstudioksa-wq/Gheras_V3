#!/usr/bin/env bash
# One-time setup of Gheras on the shared VPS (76.13.0.195). Safe to re-run.
#
# This server also runs Lizam (live production). The script touches ONLY
# Gheras: it never stops, restarts or reloads lizam or any other service. The
# one shared action, a graceful `nginx reload` to add Gheras's port-3000 site,
# happens only with --enable-site, only after `nginx -t` passes, and is undone
# automatically if Lizam isn't healthy afterwards.
#
# Usage (as root, from the folder holding backend/ and deploy/):
#   bash deploy/provision.sh                 # everything except the nginx site
#   bash deploy/provision.sh --enable-site   # then: enable the site (graceful reload)
set -euo pipefail

APP=/var/www/gheras
DATA=/var/lib/gheras
ETC=/etc/gheras
PORT=8010
SITE_PORT=3000
LIZAM_URL=https://lizamcenter.com/api/public/site-settings
SRC=$(cd "$(dirname "$0")/.." && pwd)

step() { echo; echo "== $*"; }
lizam_ok() {
  systemctl is-active --quiet lizam &&
    [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$LIZAM_URL")" = "200" ]
}

step "Lizam before anything"
lizam_ok || { echo "ABORT: Lizam is not healthy — leave everything as is and check it first"; exit 1; }
echo "Lizam OK"

step "Ports free for Gheras"
if ss -ltn | grep -q ":$PORT "; then
  systemctl is-active --quiet gheras || { echo "ABORT: port $PORT is used by something else"; exit 1; }
fi
if grep -RqsE "listen[[:space:]]+([^;]*:)?$SITE_PORT([^0-9]|$)" /etc/nginx/sites-enabled/ --exclude=gheras; then
  echo "ABORT: another nginx site already listens on $SITE_PORT"; exit 1
fi

step "System packages (no automatic service restarts)"
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l NEEDRESTART_SUSPEND=1
apt-get install -y --no-install-recommends ffmpeg python3-venv

step "Service user and folders"
id gheras >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin gheras
mkdir -p "$APP/backend" "$APP/frontend" "$DATA/media" "$ETC"
chown -R gheras:gheras "$DATA"
chmod 750 "$ETC"

step "Code"
if [ "$SRC" != "$APP" ]; then
  cp -r "$SRC/backend/." "$APP/backend/"
  [ -d "$SRC/frontend/build" ] && cp -r "$SRC/frontend/build/." "$APP/frontend/"
fi
rm -f "$APP/backend/.env"   # production settings live in $ETC/gheras.env

step "Python environment"
[ -x "$APP/venv/bin/pip" ] || python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade pip
"$APP/venv/bin/pip" install -q -r "$APP/backend/requirements_local.txt"

step "Chromium for the picture book (Playwright build: snap's can't read $DATA)"
"$APP/venv/bin/pip" install -q playwright
PLAYWRIGHT_BROWSERS_PATH="$DATA/ms-playwright" "$APP/venv/bin/playwright" install chromium
"$APP/venv/bin/playwright" install-deps chromium   # shared libraries only
chown -R gheras:gheras "$DATA/ms-playwright"
CHROME=$(ls -d "$DATA"/ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null | sort | tail -1)
[ -x "$CHROME" ] || { echo "ABORT: Chromium not found after install"; exit 1; }
echo "Chromium: $CHROME"

step "Settings file"
if [ ! -f "$ETC/gheras.env" ]; then
  install -m 640 -o root -g gheras "$SRC/deploy/gheras.env.example" "$ETC/gheras.env"
  sed -i "s#^PDF_BROWSER=.*#PDF_BROWSER=$CHROME#" "$ETC/gheras.env"
  echo "Created $ETC/gheras.env — fill in JWT_SECRET, ADMIN_PASSWORD, SECRETS_ENCRYPTION_KEY"
  echo "(and MONGO_URL if Mongo needs a password), then run this script again."
  exit 2
fi
grep -q "CHANGE_ME" "$ETC/gheras.env" && { echo "ABORT: $ETC/gheras.env still has CHANGE_ME values"; exit 1; }
sed -i "s#^PDF_BROWSER=.*#PDF_BROWSER=$CHROME#" "$ETC/gheras.env"
chown root:gheras "$ETC/gheras.env"; chmod 640 "$ETC/gheras.env"

step "Gheras service (only gheras is (re)started)"
install -m 644 "$SRC/deploy/gheras.service" /etc/systemd/system/gheras.service
systemctl daemon-reload
systemctl enable gheras
systemctl restart gheras
curl -fsS --retry 15 --retry-delay 2 --retry-connrefused "http://127.0.0.1:$PORT/api/" | grep -q healthy \
  || { echo "ERROR: Gheras didn't come up — journalctl -u gheras -n 80"; exit 1; }
echo "Gheras OK on 127.0.0.1:$PORT"

step "nginx site (port $SITE_PORT)"
install -m 644 "$SRC/deploy/nginx-gheras.conf" /etc/nginx/sites-available/gheras
if [ "${1:-}" = "--enable-site" ]; then
  ln -sf /etc/nginx/sites-available/gheras /etc/nginx/sites-enabled/gheras
  if nginx -t; then
    systemctl reload nginx
    echo "Site enabled (graceful reload)"
  else
    rm -f /etc/nginx/sites-enabled/gheras
    echo "ABORT: nginx -t failed — Gheras site removed, nothing reloaded"; exit 1
  fi
else
  echo "Installed but not enabled. Re-run with --enable-site to serve it on :$SITE_PORT."
fi

step "Lizam after"
if ! lizam_ok; then
  echo "ALERT: Lizam is not healthy after the setup — rolling back the Gheras site"
  if [ -L /etc/nginx/sites-enabled/gheras ]; then
    rm -f /etc/nginx/sites-enabled/gheras
    nginx -t && systemctl reload nginx
  fi
  exit 1
fi
echo "Lizam OK — done."
