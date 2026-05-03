#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  Nx-Citadel Intelligence Monitor — Remote Installer (dropper)
#
#  Usage (one-liner on any Linux machine):
#    curl -fsSL https://www.antonizick.com/nxcitadel/get.sh | sudo bash
#
#  With optional install flags passed through:
#    curl -fsSL https://www.antonizick.com/nxcitadel/get.sh | sudo bash -s -- --port 9000 --dir /opt/citadel --user citadel
#
#  Available flags (forwarded to install.sh):
#    --dir  PATH   Installation directory  (default: /opt/nxcitadel)
#    --user NAME   System user to run the service as (default: nxcitadel)
#    --port PORT   TCP port for the web interface (default: 8000)
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

BASE_URL="https://www.antonizick.com/nxcitadel"
PACKAGE_URL="${BASE_URL}/nxcitadel-latest.tar.gz"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

banner() { echo -e "\n${CYAN}${BOLD}━━━  $1  ━━━${RESET}"; }
ok()     { echo -e "  ${GREEN}✔${RESET}  $1"; }
info()   { echo -e "  ${CYAN}→${RESET}  $1"; }
warn()   { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
die()    { echo -e "\n${RED}${BOLD}ERROR:${RESET} $1\n"; exit 1; }

# ── Root check ────────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && die "This installer must be run as root.\n\n  Try:\n    curl -fsSL ${BASE_URL}/get.sh | sudo bash"

# ── Banner ────────────────────────────────────────────────────────────────────
clear
echo ""
echo -e "${CYAN}${BOLD}"
echo "  ███╗   ██╗██╗  ██╗       ██████╗██╗████████╗ █████╗ ██████╗ ███████╗██╗     "
echo "  ████╗  ██║╚██╗██╔╝      ██╔════╝██║╚══██╔══╝██╔══██╗██╔══██╗██╔════╝██║     "
echo "  ██╔██╗ ██║ ╚███╔╝ █████╗██║     ██║   ██║   ███████║██║  ██║█████╗  ██║     "
echo "  ██║╚██╗██║ ██╔██╗ ╚════╝██║     ██║   ██║   ██╔══██║██║  ██║██╔══╝  ██║     "
echo "  ██║ ╚████║██╔╝ ██╗      ╚██████╗██║   ██║   ██║  ██║██████╔╝███████╗███████╗"
echo "  ╚═╝  ╚═══╝╚═╝  ╚═╝       ╚═════╝╚═╝   ╚═╝   ╚═╝  ╚═╝╚═════╝ ╚══════╝╚══════╝"
echo -e "${RESET}"
echo -e "  ${BOLD}Intelligence Monitor — Remote Installer${RESET}"
echo -e "  Downloading from: ${CYAN}${BASE_URL}${RESET}"
echo ""
echo -e "  ${YELLOW}Press Ctrl-C within 5 seconds to abort…${RESET}"
sleep 5
echo ""

# ── Detect download tool ──────────────────────────────────────────────────────
banner "Phase 1 of 3 — Downloading Nx-Citadel"
echo ""

DOWNLOADER=""
if command -v curl &>/dev/null; then
  DOWNLOADER="curl"
  ok "Found curl"
elif command -v wget &>/dev/null; then
  DOWNLOADER="wget"
  ok "Found wget"
else
  die "Neither curl nor wget is available.\n\n  Install one first:\n    Debian/Ubuntu : sudo apt install curl\n    RHEL/Fedora   : sudo dnf install curl\n    Arch Linux    : sudo pacman -S curl"
fi

# ── Create temp working directory ─────────────────────────────────────────────
TMPDIR="$(mktemp -d /tmp/nxcitadel-install-XXXXXX)"
PACKAGE_FILE="${TMPDIR}/nxcitadel-latest.tar.gz"

# Always clean up the temp dir on exit (success or failure)
trap 'echo ""; info "Cleaning up temporary files…"; rm -rf "$TMPDIR"; echo ""' EXIT

info "Temporary directory: ${TMPDIR}"
info "Downloading package from:"
info "  ${PACKAGE_URL}"
echo ""

if [[ "$DOWNLOADER" == "curl" ]]; then
  curl --fail --show-error --location --progress-bar \
       -o "$PACKAGE_FILE" \
       "$PACKAGE_URL" \
    || die "Download failed.\n\n  Check that the package exists at:\n    ${PACKAGE_URL}\n\n  Also check your internet connection and DNS."
else
  wget --progress=bar:force \
       -O "$PACKAGE_FILE" \
       "$PACKAGE_URL" \
    || die "Download failed.\n\n  Check that the package exists at:\n    ${PACKAGE_URL}\n\n  Also check your internet connection and DNS."
fi

echo ""
SIZE=$(du -sh "$PACKAGE_FILE" | cut -f1)
ok "Downloaded  (${SIZE})"

# ── Extract ───────────────────────────────────────────────────────────────────
banner "Phase 2 of 3 — Extracting package"
echo ""

EXTRACT_DIR="${TMPDIR}/src"
mkdir -p "$EXTRACT_DIR"

info "Extracting to ${EXTRACT_DIR}…"
tar -xzf "$PACKAGE_FILE" -C "$EXTRACT_DIR"
ok "Package extracted"

# Locate install.sh — it lives at deploy/install.sh in current packages
# (fallback: root-level install.sh for compatibility with older archives)
INSTALL_SH=""
if   [[ -f "${EXTRACT_DIR}/deploy/install.sh" ]]; then
  INSTALL_SH="${EXTRACT_DIR}/deploy/install.sh"
elif [[ -f "${EXTRACT_DIR}/install.sh" ]]; then
  INSTALL_SH="${EXTRACT_DIR}/install.sh"
else
  die "install.sh not found in package — the archive may be corrupt.\n  Try re-downloading: ${PACKAGE_URL}"
fi
ok "Found installer at: ${INSTALL_SH#${EXTRACT_DIR}/}"

# ── Run install.sh ────────────────────────────────────────────────────────────
banner "Phase 3 of 3 — Running installer"
echo ""
info "Handing off to install.sh with arguments: ${*:-<none>}"
echo ""

# Forward all arguments (--dir, --user, --port) through to install.sh
# install.sh opens /dev/tty directly for each interactive prompt, so no
# stdin re-attachment is needed here.
bash "$INSTALL_SH" "$@"
