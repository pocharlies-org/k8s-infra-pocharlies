#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
MACHINE="$(uname -m)"

case "$MACHINE" in
  x86_64 | amd64) ARCH=amd64 ;;
  arm64 | aarch64) ARCH=arm64 ;;
  *) echo "Unsupported architecture: $MACHINE" >&2; exit 1 ;;
esac

requested="${1:-all}"
if [[ "$requested" == all ]]; then
  versions=(v1.33.13 v1.34.9)
else
  versions=("$requested")
fi

for version in "${versions[@]}"; do
  case "${version}/${OS}/${ARCH}" in
    v1.33.13/linux/amd64) expected=316d712726d857c20744c57cb36aa47cfc79bc0af7e82cebf3780244b654c073 ;;
    v1.33.13/linux/arm64) expected=9fe8aadd5aab9421978c7ac95de6fad304a3c4c0ce9dbf4127579779e0699080 ;;
    v1.33.13/darwin/amd64) expected=5c55bdb8896681b6921cad3cff20a09b424887bb5bcb771de84b42e4322faeeb ;;
    v1.33.13/darwin/arm64) expected=17e3d0a6d9908914c67370b329b6aa9489de7ca035ecd5b7773456cdbe318bbd ;;
    v1.34.9/linux/amd64) expected=73bb6f5063caadae1e73a39de018d8ad21755984bea35358484db817859e7634 ;;
    v1.34.9/linux/arm64) expected=63317b16a5264af47169b54dafd1878fed29031ebc8367960dd3b88484334e04 ;;
    v1.34.9/darwin/amd64) expected=0dc573119159e7ca4f77b3853903c27750f339d23776040493ec6fbece110aa0 ;;
    v1.34.9/darwin/arm64) expected=fb4448843b83ba82ccfd1d634764ef29a9b47d830a896e87bde496f876a980ac ;;
    *) echo "Unsupported kubectl/platform: ${version}/${OS}/${ARCH}" >&2; exit 1 ;;
  esac

  destination="$ROOT/.tools/kubectl-${version}"
  mkdir -p "$(dirname "$destination")"
  temporary="$(mktemp "${destination}.XXXXXX")"
  curl --fail --silent --show-error --location \
    --proto '=https' --tlsv1.2 \
    "https://dl.k8s.io/release/${version}/bin/${OS}/${ARCH}/kubectl" \
    --output "$temporary"

  actual="$(shasum -a 256 "$temporary" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    rm -f "$temporary"
    echo "kubectl checksum mismatch: expected $expected, got $actual" >&2
    exit 1
  fi
  chmod 0755 "$temporary"
  mv -f "$temporary" "$destination"
  echo "$destination"
done
