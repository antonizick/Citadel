#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  Nx-Citadel — Build Deployment Package
#  Creates a deployable tar.gz containing only the distributable application
#  code — no user data, configuration, secrets, logs, or virtual environment.
#
#  Usage: bash build_package.sh
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; RESET='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(dirname "$SCRIPT_DIR")"   # parent of deploy/ — the application root
VERSION=$(date -u +"%Y%m%d_%H%M%S")
PACKAGE_NAME="nxcitadel-${VERSION}.tar.gz"
OUTPUT="$SCRIPT_DIR/$PACKAGE_NAME"   # deploy/nxcitadel-<timestamp>.tar.gz
LATEST="$SCRIPT_DIR/nxcitadel-latest.tar.gz"

echo ""
echo -e "${CYAN}${BOLD}Nx-Citadel — Build Deployment Package${RESET}"
echo ""
echo -e "  Source  : $APP_ROOT"
echo -e "  Package : $OUTPUT"
echo ""
echo -e "  ${YELLOW}Excluded from package (user-specific / runtime):${RESET}"
echo -e "    data/              — user configuration, interests, resources, reports"
echo -e "    logs/              — application log files"
echo -e "    .venv/             — Python virtual environment (rebuilt on install)"
echo -e "    .claude/           — Claude Code IDE settings"
echo -e "    __pycache__/       — Python bytecode cache"
echo -e "    *.pyc / *.pyo      — compiled Python files"
echo -e "    deploy/*.tar.gz    — previous deployment packages"
echo ""

cd "$APP_ROOT"

TMPOUT="$(mktemp /tmp/nxcitadel-build-XXXXXX.tar.gz)"

tar -czf "$TMPOUT" \
  --exclude='./data' \
  --exclude='./logs' \
  --exclude='./.venv' \
  --exclude='./.claude' \
  --exclude='./__pycache__' \
  --exclude='./*/__pycache__' \
  --exclude='./*/*/__pycache__' \
  --exclude='./*/*/*/__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='./.git' \
  --exclude='./.citadel.pid' \
  --exclude='./deploy/nxcitadel-*.tar.gz' \
  --exclude='./deploy/*.zip' \
  .

mv "$TMPOUT" "$OUTPUT"

# Also write a stable "latest" copy for the dropper script
cp "$OUTPUT" "$LATEST"

SIZE=$(du -sh "$OUTPUT" | cut -f1)

echo -e "${GREEN}${BOLD}Packages created:${RESET}"
echo -e "  ${PACKAGE_NAME}  (${SIZE})  — timestamped archive"
echo -e "  nxcitadel-latest.tar.gz  (${SIZE})  — stable name for dropper script"
echo ""
echo -e "  ${BOLD}Contents of this package:${RESET}"
tar -tzf "$OUTPUT" | grep -v '__pycache__' | grep -v '\.pyc' | head -40
echo "  …"
echo ""
echo -e "  ${BOLD}To deploy — upload these two files to your web server:${RESET}"
echo ""
echo -e "    nxcitadel-latest.tar.gz  → https://www.antonizick.com/nxcitadel/nxcitadel-latest.tar.gz"
echo -e "    get.sh                   → https://www.antonizick.com/nxcitadel/get.sh"
echo ""
echo -e "  ${BOLD}One-liner to install on any Linux machine:${RESET}"
echo ""
echo -e "    curl -fsSL https://www.antonizick.com/nxcitadel/get.sh | sudo bash"
echo ""
echo -e "  ${BOLD}With optional flags:${RESET}"
echo -e "    curl -fsSL https://www.antonizick.com/nxcitadel/get.sh | sudo bash -s -- --port 9000"
echo -e "    curl -fsSL https://www.antonizick.com/nxcitadel/get.sh | sudo bash -s -- --dir /opt/citadel --user citadel"
echo ""
echo -e "  ${BOLD}Or manual (scp) deploy:${RESET}"
echo -e "    scp $PACKAGE_NAME user@server:/tmp/"
echo -e "    ssh user@server 'mkdir /tmp/nx && tar -xzf /tmp/$PACKAGE_NAME -C /tmp/nx && sudo bash /tmp/nx/deploy/install.sh'"
echo ""
echo -e "  ${BOLD}Default admin credentials (change immediately after first login):${RESET}"
echo -e "    Username : admin"
echo -e "    Password : admin"
echo ""
