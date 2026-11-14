#!/bin/bash
# ca8-undo.sh - remove EVERY iptables INPUT rule whose comment starts with "ca8"
# (ca8-SC-5299, ca8-pretest-*, any future ca8-<tag>). Safe to run repeatedly.
# Exit 0 when no ca8 rule remains, 1 otherwise. Absolute paths: runs under systemd's minimal PATH.
# Rewritten 2026-11-14 (SC-5299 CA8): the old pretest undo piped "-D INPUT ..." to sh without
# the iptables command (exit 127) and left the LAN cut.
IPT=/usr/sbin/iptables
LOGGER=/usr/bin/logger
MATCH='--comment "?ca8'
removed=0
failed=0
for pass in $(seq 1 20); do
  mapfile -t specs < <("$IPT" -w -S INPUT | /usr/bin/grep -E -- "$MATCH" | /usr/bin/sed 's/^-A INPUT //')
  [ "${#specs[@]}" -eq 0 ] && break
  for spec in "${specs[@]}"; do
    # iptables -S output is shell-quoted (comments with spaces come double-quoted): eval re-splits it.
    if eval "\"$IPT\" -w -D INPUT $spec"; then
      removed=$((removed + 1))
    else
      failed=$((failed + 1))
    fi
  done
done
remaining=$("$IPT" -w -S INPUT | /usr/bin/grep -c -E -- "$MATCH")
if [ "$remaining" -eq 0 ]; then
  "$LOGGER" -t ca8-undo "OK: removed $removed ca8 rule(s), 0 remain (delete errors: $failed)"
  echo "ca8-undo: removed $removed, remaining 0"
  exit 0
fi
"$LOGGER" -p user.err -t ca8-undo "FAIL: removed $removed ca8 rule(s), $remaining REMAIN (delete errors: $failed)"
echo "ca8-undo: removed $removed, REMAINING $remaining" >&2
exit 1
