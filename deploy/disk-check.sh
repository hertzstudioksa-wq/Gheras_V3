#!/usr/bin/env bash
# Warn before the disk fills up (on the laptop a full C: stopped MongoDB twice).
# Read-only: it looks at free space and writes a warning to the system log; with
# GHERAS_ALERT_EMAIL and a working `mail` command it also sends an email.
#
# Install once (as root):
#   install -m 755 /root/gheras-src/deploy/disk-check.sh /usr/local/bin/gheras-disk-check
#   echo '*/30 * * * * root /usr/local/bin/gheras-disk-check' > /etc/cron.d/gheras-disk-check
set -euo pipefail

LIMIT=${GHERAS_DISK_LIMIT_PCT:-85}
for mount in / /var/lib/gheras; do
  [ -d "$mount" ] || continue
  used=$(df -P "$mount" | awk 'NR==2 {gsub("%", "", $5); print $5}')
  if [ "$used" -ge "$LIMIT" ]; then
    msg="Gheras server disk $mount is ${used}% full (limit ${LIMIT}%). Free space before MongoDB or uploads fail."
    logger -t gheras-disk "$msg"
    if [ -n "${GHERAS_ALERT_EMAIL:-}" ] && command -v mail >/dev/null 2>&1; then
      echo "$msg" | mail -s "Gheras: disk ${used}% full" "$GHERAS_ALERT_EMAIL"
    fi
  fi
done
