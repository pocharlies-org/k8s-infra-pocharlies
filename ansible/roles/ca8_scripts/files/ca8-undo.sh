#!/bin/bash
# ca8-undo.sh - remove EVERY iptables INPUT rule whose comment starts with "ca8"
# (ca8-SC-5299, ca8-pretest-*, any future ca8-<tag>). Safe to run repeatedly.
# Exit 0 when no ca8 rule remains, 1 otherwise. Absolute paths: runs under systemd's minimal PATH.
# Rewritten 2026-11-14 (SC-5299 CA8): the old pretest undo piped "-D INPUT ..." to sh without
# the iptables command (exit 127) and left the LAN cut. Second rewrite the same day (security
# review of PR #523): rule text is never re-parsed by the shell. Rules are deleted by NUMBER,
# highest first, read from `iptables -L INPUT --line-numbers -n`; each number is re-read and
# re-checked right before its delete. The script only lists and deletes: it never adds, flushes
# or changes a policy.
IPT=/usr/sbin/iptables
LOGGER=/usr/bin/logger
AWK=/usr/bin/awk
SORT=/usr/bin/sort
MAX_PASSES=20

# A listing line is a ca8 rule when its first comment field "/* ... */" starts with "ca8".
is_ca8='{ i = index($0, "/* "); if (i > 0 && substr($0, i + 3, 3) == "ca8") { found = 1 } }'

# Rule numbers of the ca8 rules in INPUT, highest first.
ca8_numbers() {
  "$IPT" -w -L INPUT --line-numbers -n \
    | "$AWK" '$1 ~ /^[0-9]+$/ { i = index($0, "/* "); if (i > 0 && substr($0, i + 3, 3) == "ca8") print $1 }' \
    | "$SORT" -rn
}

# True when rule number $1 of INPUT is (still) a ca8 rule.
still_ca8() {
  "$IPT" -w -L INPUT "$1" -n 2>/dev/null | "$AWK" "$is_ca8"' END { exit found ? 0 : 1 }'
}

removed=0
failed=0
for pass in $(seq 1 "$MAX_PASSES"); do
  mapfile -t nums < <(ca8_numbers)
  [ "${#nums[@]}" -eq 0 ] && break
  for n in "${nums[@]}"; do
    [[ "$n" =~ ^[0-9]+$ ]] || continue
    # Another writer (kube-router, kube-proxy, tailscale) may have shifted the numbers since the
    # listing: delete only if rule $n is still a ca8 rule; otherwise the next pass re-lists.
    if ! still_ca8 "$n"; then
      continue 2
    fi
    if "$IPT" -w -D INPUT "$n"; then
      removed=$((removed + 1))
    else
      failed=$((failed + 1))
    fi
  done
done
mapfile -t left < <(ca8_numbers)
remaining=${#left[@]}
if [ "$remaining" -eq 0 ]; then
  "$LOGGER" -t ca8-undo "OK: removed $removed ca8 rule(s), 0 remain (delete errors: $failed)"
  echo "ca8-undo: removed $removed, remaining 0"
  exit 0
fi
"$LOGGER" -p user.err -t ca8-undo "FAIL: removed $removed ca8 rule(s), $remaining REMAIN (delete errors: $failed)"
echo "ca8-undo: removed $removed, REMAINING $remaining" >&2
exit 1
