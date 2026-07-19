#!/usr/bin/env bash
set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
RESET='\033[0m'

info() { printf "${BOLD}%s${RESET}\n" "$*"; }
ok()   { printf "${GREEN}✓${RESET} %s\n" "$*"; }
warn() { printf "${YELLOW}⚠${RESET} %s\n" "$*"; }
die()  { printf "${RED}✗${RESET} %s\n" "$*" >&2; exit 1; }

case "$(uname -s)" in
  Darwin) PLATFORM="macOS" ;;
  Linux)  PLATFORM="Linux" ;;
  *)      die "Unsupported platform: $(uname -s)" ;;
esac

info "Installing update-all on ${PLATFORM}..."

# --- Ensure uv is available ---
if ! command -v uv >/dev/null 2>&1; then
  info "uv not found — bootstrapping..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || die "uv install failed. Install manually: https://docs.astral.sh/uv/getting-started/installation/"
  ok "uv installed: $(uv --version)"
else
  ok "uv found: $(uv --version)"
fi

# --- Install update-all ---
uv tool install "update-all@latest" --force --python 3.11
ok "update-all installed"

# Ensure the uv tool bin dir is on PATH
UV_BIN_DIR="$(uv tool bin 2>/dev/null || echo "$HOME/.local/bin")"
export PATH="$UV_BIN_DIR:$PATH"

if ! command -v update-all >/dev/null 2>&1; then
  warn "'update-all' not found in PATH. Add this to your shell profile:"
  printf "  export PATH=\"%s:\$PATH\"\n\n" "$UV_BIN_DIR"
fi

# --- Optionally install the scheduler ---
INSTALL_AGENT=n
if [ -e /dev/tty ]; then
  printf "\nInstall background scheduler (runs update-all every hour via "
  [ "$PLATFORM" = "macOS" ] && printf "LaunchAgent" || printf "systemd timer"
  printf ")? [y/N] "
  read -r INSTALL_AGENT </dev/tty || INSTALL_AGENT=n
fi

case "$INSTALL_AGENT" in
  [yY]|[yY][eE][sS])
    if update-all --install-agent; then
      ok "Scheduler installed"
    else
      warn "Scheduler installation reported an error (see above)."
    fi
    ;;
  *)
    info "Run 'update-all --install-agent' anytime to enable the scheduler."
    ;;
esac

printf "\nRun ${GREEN}update-all${RESET} to update all your package managers.\n"
