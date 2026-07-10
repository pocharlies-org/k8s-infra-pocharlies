#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="v1.33.13"
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
MACHINE="$(uname -m)"

case "$MACHINE" in
  x86_64 | amd64) ARCH=amd64 ;;
  arm64 | aarch64) ARCH=arm64 ;;
  *) echo "Unsupported architecture: $MACHINE" >&2; exit 1 ;;
esac

case "${OS}/${ARCH}" in
  linux/amd64) EXPECTED=316d712726d857c20744c57cb36aa47cfc79bc0af7e82cebf3780244b654c073 ;;
  linux/arm64) EXPECTED=9fe8aadd5aab9421978c7ac95de6fad304a3c4c0ce9dbf4127579779e0699080 ;;
  darwin/amd64) EXPECTED=5c55bdb8896681b6921cad3cff20a09b424887bb5bcb771de84b42e4322faeeb ;;
  darwin/arm64) EXPECTED=17e3d0a6d9908914c67370b329b6aa9489de7ca035ecd5b7773456cdbe318bbd ;;
  *) echo "Unsupported platform: ${OS}/${ARCH}" >&2; exit 1 ;;
esac

DEST="$ROOT/.tools/kubectl-${VERSION}"
mkdir -p "$(dirname "$DEST")"
TMP="$(mktemp "${DEST}.XXXXXX")"
trap 'rm -f "$TMP"' EXIT

curl --fail --silent --show-error --location \
  --proto '=https' --tlsv1.2 \
  "https://dl.k8s.io/release/${VERSION}/bin/${OS}/${ARCH}/kubectl" \
  --output "$TMP"

ACTUAL="$(shasum -a 256 "$TMP" | awk '{print $1}')"
if [[ "$ACTUAL" != "$EXPECTED" ]]; then
  echo "kubectl checksum mismatch: expected $EXPECTED, got $ACTUAL" >&2
  exit 1
fi

chmod 0755 "$TMP"
mv -f "$TMP" "$DEST"
trap - EXIT
echo "$DEST"
