#!/usr/bin/env bash
set -euo pipefail

info() { printf '%s\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

case "$(uname -s)" in
  Darwin) GOOS=darwin ;;
  Linux) GOOS=linux ;;
  *) die "Unsupported operating system: $(uname -s)" ;;
esac
case "$(uname -m)" in
  x86_64|amd64) GOARCH=amd64 ;;
  aarch64|arm64) GOARCH=arm64 ;;
  *) die "Unsupported architecture: $(uname -m)" ;;
esac

command -v curl >/dev/null 2>&1 || die "curl is required"
command -v tar >/dev/null 2>&1 || die "tar is required"
if command -v sha256sum >/dev/null 2>&1; then HASH_TOOL=sha256sum
elif command -v shasum >/dev/null 2>&1; then HASH_TOOL=shasum
else die "sha256sum or shasum is required"
fi

RELEASE_JSON="$(curl -fsSL https://api.github.com/repos/cruffinoni/update-all/releases/latest)" || die "Could not fetch the latest GitHub release"
VERSION="$(printf '%s' "$RELEASE_JSON" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"v\([^"]*\)".*/\1/p' | head -n 1)"
[ -n "$VERSION" ] || die "Could not read latest release version"
ARCHIVE="update-all_${VERSION}_${GOOS}_${GOARCH}.tar.gz"
BASE_URL="https://github.com/cruffinoni/update-all/releases/download/v${VERSION}"
CHECKSUMS="update-all_${VERSION}_checksums.txt"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
curl -fsSL "$BASE_URL/$ARCHIVE" -o "$TMP_DIR/$ARCHIVE" || die "Could not download $ARCHIVE"
curl -fsSL "$BASE_URL/$CHECKSUMS" -o "$TMP_DIR/$CHECKSUMS" || die "Could not download release checksums"
cd "$TMP_DIR"
EXPECTED="$(awk -v file="$ARCHIVE" '$2 == file {print $1}' "$CHECKSUMS")"
[ -n "$EXPECTED" ] || die "No checksum found for $ARCHIVE"
if [ "$HASH_TOOL" = sha256sum ]; then ACTUAL="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
else ACTUAL="$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')"
fi
[ "$EXPECTED" = "$ACTUAL" ] || die "Release archive checksum mismatch"
tar -xzf "$ARCHIVE" update-all || die "Could not extract update-all"

INSTALL_DIR="${UPDATE_ALL_INSTALL_DIR:-$HOME/.local/bin}"
mkdir -p "$INSTALL_DIR"
install -m 0755 update-all "$INSTALL_DIR/update-all"
export PATH="$INSTALL_DIR:$PATH"
info "Installed update-all $VERSION to $INSTALL_DIR/update-all"

info "Run 'update-all' to update your package managers."
