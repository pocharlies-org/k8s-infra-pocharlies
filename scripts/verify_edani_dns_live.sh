#!/usr/bin/env bash
# verify_edani_dns_live.sh — INFRA-902 C2: live check that every e-dani.com name
# pinned by scripts/gen_coredns_edani.py answers traefik-lan -- the LAN VIP
# 192.168.50.240 or a k3s Service ClusterIP (10.43.0.0/16) -- from EVERY
# kube-dns endpoint, and never a public IP.
#
# The names come ONLY from `python3 scripts/gen_coredns_edani.py --list-fixed`
# (the single source of pinned names; a hand-made list here would be exactly
# the class of drift INFRA-902 fixes).  Extra names may be passed as arguments
# and are checked with the same rule: that is how the failure mode is
# demonstrated on a name that is NOT pinned (C2a) and how ad-hoc checks run.
#
# Exit codes:
#   0  every answer is the LAN VIP or a 10.43.0.0/16 ClusterIP (empty answers
#      are reported but do not fail the check -- the criterion is "no public IP")
#   1  at least one name x endpoint answered a public IP
#   2  environment error (no kube-dns endpoints, --list-fixed empty)
#
# Reusable: the S3 probe runs it in-cluster (image alpine/k8s carries `dig`)
# and it is the tool for any future "did a pin regress" question.  It uses
# `dig` when present; where dig is absent (this control host) it falls back to
# python3 + dnspython, which answers the same A records the same way.
#
# KUBECONFIG defaults to ~/.kube/config (/etc/rancher/k3s/k3s.yaml is root-only).
set -uo pipefail

export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
REPO="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
VIP="192.168.50.240"

dns_query() { # dns_query <endpoint-ip> <name> -> A answers, one per line
  local ep="$1" name="$2"
  if command -v dig >/dev/null 2>&1; then
    dig +short "@${ep}" "${name}" A
  else
    python3 - "$ep" "$name" <<'PY'
import sys
import dns.resolver

ep, name = sys.argv[1], sys.argv[2]
res = dns.resolver.Resolver(configure=False)
res.nameservers = [ep]
res.timeout = 5
try:
    for a in res.resolve(name, "A"):
        print(a.address)
except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer,
        dns.resolver.NoNameservers, dns.exception.Timeout):
    pass
PY
  fi
}

is_allowed() { # LAN VIP or k3s Service ClusterIP range
  local ip="$1"
  [[ "$ip" == "$VIP" || "$ip" =~ ^10\.43\. ]]
}

ENDPOINTS=()
# `|| [[ -n "$ip" ]]`: the jsonpath output has no trailing newline and `read`
# would otherwise drop the last endpoint.
while IFS= read -r ip || [[ -n "$ip" ]]; do
  [[ -n "$ip" ]] && ENDPOINTS+=("$ip")
done < <(kubectl -n kube-system get endpoints kube-dns \
  -o jsonpath='{.subsets[*].addresses[*].ip}' | tr ' ' '\n')
if [[ ${#ENDPOINTS[@]} -eq 0 ]]; then
  echo "ERROR: kube-dns no tiene endpoints" >&2
  exit 2
fi

# endpoint pod IP -> node, so the output says where each replica answers from
declare -A NODE_OF
while read -r ip node; do
  [[ -n "$ip" ]] && NODE_OF["$ip"]="$node"
done < <(kubectl -n kube-system get pods -l k8s-app=kube-dns \
  -o jsonpath='{range .items[*]}{.status.podIP} {.spec.nodeName}{"\n"}{end}')

NAMES=()
while IFS= read -r n || [[ -n "$n" ]]; do
  [[ -n "$n" ]] && NAMES+=("$n")
done < <(python3 "$REPO/scripts/gen_coredns_edani.py" --list-fixed)
if [[ ${#NAMES[@]} -eq 0 ]]; then
  echo "ERROR: --list-fixed no devolvió nombres" >&2
  exit 2
fi
EXTRA=("$@")
ALL_NAMES=("${NAMES[@]}" "${EXTRA[@]}")

echo "# verify_edani_dns_live: ${#ALL_NAMES[@]} nombres x ${#ENDPOINTS[@]} endpoints kube-dns"
echo "# permitidos: ${VIP} y ClusterIP 10.43.0.0/16"

fail=0
checked=0
empty=0
for ep in "${ENDPOINTS[@]}"; do
  node="${NODE_OF[$ep]:-?}"
  for name in "${ALL_NAMES[@]}"; do
    answers="$(dns_query "$ep" "$name")"
    checked=$((checked + 1))
    if [[ -z "$answers" ]]; then
      empty=$((empty + 1))
      echo "SIN-RESPUESTA  ep=${ep} (${node})  ${name}"
      continue
    fi
    bad=""
    while IFS= read -r ip; do
      [[ -n "$ip" ]] || continue
      is_allowed "$ip" || bad+=" ${ip}"
    done <<<"$answers"
    flat="$(echo "$answers" | tr '\n' ' ')"
    if [[ -n "$bad" ]]; then
      fail=1
      echo "PUBLICA  ep=${ep} (${node})  ${name} ->${bad}"
    else
      echo "ok  ep=${ep} (${node})  ${name} -> ${flat}"
    fi
  done
done

echo "----"
echo "consultas=${checked} endpoints=${#ENDPOINTS[@]} nombres=${#ALL_NAMES[@]} (fijados=${#NAMES[@]} extra=${#EXTRA[@]}) sin-respuesta=${empty}"
if [[ $fail -eq 1 ]]; then
  echo "FALLO: al menos una respuesta con IP publica"
  exit 1
fi
echo "OK: ninguna IP publica en ${checked} consultas"
