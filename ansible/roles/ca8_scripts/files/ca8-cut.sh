#!/bin/bash
# ca8-cut.sh [tag] [undo_after_seconds]  - SC-5299 CA8 firewall cut test on atlantic.
# Schedules the automatic undo (systemd timer -> /usr/local/sbin/ca8-undo.sh) plus a backup undo
# timer (<unit>-backup, at secs+900) BEFORE inserting any DROP rule; if either schedule fails,
# nothing is cut.
# CA8_DRY_RUN=1 prints the commands without executing them.
set -u
TAG="${1:-SC-5299}"
SECS="${2:-120}"
IPT=/usr/sbin/iptables
LOGGER=/usr/bin/logger
SYSTEMD_RUN=/usr/bin/systemd-run
UNDO=/usr/local/sbin/ca8-undo.sh
SOURCES="100.82.12.28 100.73.153.70 100.93.188.99 100.83.56.98 192.168.50.0/24"

if ! [[ "$TAG" =~ ^[A-Za-z0-9._-]+$ ]]; then echo "ca8-cut: invalid tag '$TAG'" >&2; exit 2; fi
if ! [[ "$SECS" =~ ^[0-9]+$ ]] || [ "$SECS" -lt 10 ] || [ "$SECS" -gt 5400 ]; then
  echo "ca8-cut: undo_after_seconds must be 10..5400 (got '$SECS')" >&2; exit 2
fi
COMMENT="ca8-$TAG"
UNIT="ca8-undo-$TAG-$(date +%s)"
BACKUP_UNIT="$UNIT-backup"
BACKUP_SECS=$((SECS + 900))

run() {
  if [ "${CA8_DRY_RUN:-0}" = 1 ]; then echo "DRY-RUN: $*"; else "$@"; fi
}

[ -x "$UNDO" ] || { echo "ca8-cut: $UNDO missing or not executable, refusing to cut" >&2; exit 3; }

# 1) Safety net first.
if ! run "$SYSTEMD_RUN" --unit="$UNIT" --on-active="$SECS" "$UNDO"; then
  echo "ca8-cut: could not schedule $UNIT, NOT cutting" >&2
  "$LOGGER" -p user.err -t "$COMMENT" "undo schedule failed, cut aborted"
  exit 4
fi
if [ "${CA8_DRY_RUN:-0}" != 1 ] && ! /usr/bin/systemctl list-timers --all --no-legend | /usr/bin/grep -q "$UNIT"; then
  echo "ca8-cut: timer $UNIT not listed, NOT cutting" >&2
  "$LOGGER" -p user.err -t "$COMMENT" "undo timer $UNIT not listed, cut aborted"
  exit 4
fi

# 1b) Backup safety net (in case the first undo fails or is cancelled).
if ! run "$SYSTEMD_RUN" --unit="$BACKUP_UNIT" --on-active="$BACKUP_SECS" "$UNDO"; then
  echo "ca8-cut: could not schedule $BACKUP_UNIT, NOT cutting" >&2
  "$LOGGER" -p user.err -t "$COMMENT" "backup undo schedule failed, cut aborted"
  run /usr/bin/systemctl stop "$UNIT.timer"
  exit 4
fi
if [ "${CA8_DRY_RUN:-0}" != 1 ] && ! /usr/bin/systemctl list-timers --all --no-legend | /usr/bin/grep -q "$BACKUP_UNIT"; then
  echo "ca8-cut: timer $BACKUP_UNIT not listed, NOT cutting" >&2
  "$LOGGER" -p user.err -t "$COMMENT" "backup undo timer $BACKUP_UNIT not listed, cut aborted"
  /usr/bin/systemctl stop "$UNIT.timer"
  exit 4
fi

# 2) Cut.
for s in $SOURCES; do
  run "$IPT" -w -I INPUT -s "$s" -m comment --comment "$COMMENT" -j DROP
done
if [ "${CA8_DRY_RUN:-0}" = 1 ]; then
  echo "ca8-cut: DRY-RUN: no rules applied (comment $COMMENT; would undo via $UNIT in ${SECS}s, backup $BACKUP_UNIT in ${BACKUP_SECS}s)"
  exit 0
fi
"$LOGGER" -t "$COMMENT" "cut rules applied; automatic undo $UNIT in ${SECS}s, backup $BACKUP_UNIT in ${BACKUP_SECS}s"
echo "ca8-cut: cut applied with comment $COMMENT; undo unit $UNIT fires in ${SECS}s, backup $BACKUP_UNIT in ${BACKUP_SECS}s"
