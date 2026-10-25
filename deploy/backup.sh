#!/usr/bin/env bash
# Daily backup of Gheras only: the gheras_prod database (mongodump, read-only)
# and the media folder. Lizam shares this server and its MongoDB: this script
# dumps ONE database by name and never stops, restarts or reconfigures anything.
#
# Install once (as root):
#   install -m 750 /root/gheras-src/deploy/backup.sh /usr/local/bin/gheras-backup
#   echo '30 3 * * * root /usr/local/bin/gheras-backup >> /var/log/gheras-backup.log 2>&1' > /etc/cron.d/gheras-backup
set -euo pipefail

ENV_FILE=/etc/gheras/gheras.env
DEST=${GHERAS_BACKUP_DIR:-/var/backups/gheras}
KEEP_DAYS=${GHERAS_BACKUP_KEEP_DAYS:-14}

MONGO_URL=$(grep -E '^MONGO_URL=' "$ENV_FILE" | cut -d= -f2- || true)
DB_NAME=$(grep -E '^DB_NAME=' "$ENV_FILE" | cut -d= -f2- || true)
MEDIA=$(grep -E '^STORAGE_DIR=' "$ENV_FILE" | cut -d= -f2- || true)
MONGO_URL=${MONGO_URL:-mongodb://127.0.0.1:27017}
DB_NAME=${DB_NAME:-gheras_prod}
MEDIA=${MEDIA:-/var/lib/gheras/media}

case "$DB_NAME" in
  gheras*) ;;
  *) echo "refusing to back up a database not named gheras*: $DB_NAME" >&2; exit 1 ;;
esac

stamp=$(date +%F)
mkdir -p "$DEST"
chmod 700 "$DEST"

echo "[$(date -Is)] dumping $DB_NAME"
nice -n 10 mongodump --uri="$MONGO_URL" --db="$DB_NAME" --gzip --archive="$DEST/db-$stamp.archive.gz" --quiet

if [ -d "$MEDIA" ]; then
  # Incremental snapshots: unchanged files are hardlinks to yesterday's copy, so
  # each day costs only what changed (a full tar of hundreds of GB would not).
  echo "[$(date -Is)] snapshot $MEDIA"
  mkdir -p "$DEST/media"
  link=()
  [ -d "$DEST/media/latest" ] && link=(--link-dest="$DEST/media/latest")
  nice -n 10 rsync -a --delete "${link[@]}" "$MEDIA/" "$DEST/media/$stamp/"
  ln -sfn "$DEST/media/$stamp" "$DEST/media/latest"
  find "$DEST/media" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +"$KEEP_DAYS" -exec rm -rf {} +
fi

find "$DEST" -maxdepth 1 -type f -name 'db-*.archive.gz' -mtime +"$KEEP_DAYS" -delete
echo "[$(date -Is)] done: $(du -sh "$DEST" | cut -f1) in $DEST"
# Off the server too (recommended): rclone sync /var/backups/gheras remote:gheras-backups

# Restore (only when needed, into gheras_prod only):
#   mongorestore --uri="$MONGO_URL" --nsInclude="gheras_prod.*" --gzip --archive=/var/backups/gheras/db-YYYY-MM-DD.archive.gz --drop
