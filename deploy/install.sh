#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  Nx-Citadel Intelligence Monitor — Installer / Updater
#  Usage: sudo bash install.sh [--dir /opt/nxcitadel] [--user nxcitadel] [--port 8000]
#
#  Options:
#    --dir  PATH   Installation directory  (default: /opt/nxcitadel)
#    --user NAME   System user to run the service as (default: nxcitadel)
#    --port PORT   TCP port for the web interface (default: 8000)
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
INSTALL_DIR="/opt/nxcitadel"
SERVICE_USER="nxcitadel"
APP_PORT="8000"
SERVICE_NAME="nxcitadel"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

banner() { echo -e "\n${CYAN}${BOLD}━━━  $1  ━━━${RESET}"; }
ok()     { echo -e "  ${GREEN}✔${RESET}  $1"; }
info()   { echo -e "  ${CYAN}→${RESET}  $1"; }
warn()   { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
die()    { echo -e "\n${RED}${BOLD}ERROR:${RESET} $1\n"; exit 1; }
step()   { echo -e "\n  ${BOLD}$1${RESET}"; }

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --dir)   INSTALL_DIR="$2"; shift 2 ;;
    --user)  SERVICE_USER="$2"; shift 2 ;;
    --port)  APP_PORT="$2"; shift 2 ;;
    *) die "Unknown option: $1\nUsage: sudo bash install.sh [--dir PATH] [--user NAME] [--port PORT]" ;;
  esac
done

# ── Root check ────────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && die "This installer must be run as root. Try: sudo bash install.sh"

# ── Detect existing installation ──────────────────────────────────────────────
EXISTING_INSTALL=false
SERVICE_WAS_RUNNING=false

if [[ -d "$INSTALL_DIR" ]] && [[ -f "$INSTALL_DIR/run.py" || -f "$INSTALL_DIR/app/main.py" ]]; then
  EXISTING_INSTALL=true
fi

if $EXISTING_INSTALL && systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
  SERVICE_WAS_RUNNING=true
fi

# Upgrade intent flags — resolved by prompts below if existing install found
OVERRIDE_CODE=true
OVERRIDE_DATA=false

# ── Banner ────────────────────────────────────────────────────────────────────
[[ -t 1 ]] && clear || true
echo ""
echo -e "${CYAN}${BOLD}"
echo "  ███╗   ██╗██╗  ██╗       ██████╗██╗████████╗ █████╗ ██████╗ ███████╗██╗     "
echo "  ████╗  ██║╚██╗██╔╝      ██╔════╝██║╚══██╔══╝██╔══██╗██╔══██╗██╔════╝██║     "
echo "  ██╔██╗ ██║ ╚███╔╝ █████╗██║     ██║   ██║   ███████║██║  ██║█████╗  ██║     "
echo "  ██║╚██╗██║ ██╔██╗ ╚════╝██║     ██║   ██║   ██╔══██║██║  ██║██╔══╝  ██║     "
echo "  ██║ ╚████║██╔╝ ██╗      ╚██████╗██║   ██║   ██║  ██║██████╔╝███████╗███████╗"
echo "  ╚═╝  ╚═══╝╚═╝  ╚═╝       ╚═════╝╚═╝   ╚═╝   ╚═╝  ╚═╝╚═════╝ ╚══════╝╚══════╝"
echo -e "${RESET}"

if $EXISTING_INSTALL; then
  echo -e "  ${BOLD}Intelligence Monitor — Updater${RESET}"
else
  echo -e "  ${BOLD}Intelligence Monitor — Installer v1.0${RESET}"
fi

echo ""
echo -e "  This script will:"
if $EXISTING_INSTALL; then
  echo -e "    1. Detect your existing installation and ask what to update"
  echo -e "    2. Optionally update system files (app code, templates, static assets)"
  echo -e "    3. Optionally replace data and configuration files"
  echo -e "    4. Refresh Python dependencies if code is updated"
  echo -e "    5. Ensure the systemd service is configured correctly"
  echo -e "    6. Restart (or start) the service as needed"
else
  echo -e "    1. Check for Python 3.10+ (auto-installs Python 3.11 if needed)"
  echo -e "    2. Create a dedicated system user to run Citadel"
  echo -e "    3. Copy application files to ${BOLD}${INSTALL_DIR}${RESET}"
  echo -e "    4. Install Python dependencies into a private virtual environment"
  echo -e "    5. Install and enable a systemd service for auto-start on boot"
  echo -e "    6. Start the service and verify it is running"
fi
echo ""
echo -e "  ${BOLD}Parameters:${RESET}"
echo -e "    Install directory : ${CYAN}${INSTALL_DIR}${RESET}"
echo -e "    Service user      : ${CYAN}${SERVICE_USER}${RESET}"
echo -e "    Application port  : ${CYAN}${APP_PORT}${RESET}"
echo -e "    Systemd service   : ${CYAN}${SERVICE_NAME}.service${RESET}"
echo ""
echo -e "  ${YELLOW}Press Ctrl-C within 5 seconds to abort…${RESET}"
sleep 5
echo ""

# ── Upgrade prompts (existing install only) ───────────────────────────────────
if $EXISTING_INSTALL; then
  echo -e "  ${YELLOW}${BOLD}━━━  Existing installation detected  ━━━${RESET}"
  echo ""
  echo -e "  ${CYAN}→${RESET}  Nx-Citadel found at: ${BOLD}${INSTALL_DIR}${RESET}"

  if $SERVICE_WAS_RUNNING; then
    echo -e "  ${CYAN}→${RESET}  Service '${SERVICE_NAME}' is currently ${GREEN}running${RESET}"
    echo -e "       (it will be stopped during a code update and restarted when complete)"
  else
    echo -e "  ${CYAN}→${RESET}  Service '${SERVICE_NAME}' is currently ${YELLOW}stopped${RESET}"
  fi

  # Determine whether we can interactively prompt.
  # When piped through sudo or a non-TTY context /dev/tty may be absent.
  if [[ -e /dev/tty ]]; then
    TTY_AVAILABLE=true
  else
    TTY_AVAILABLE=false
    echo ""
    warn "No interactive terminal detected — using safe defaults:"
    warn "  Update system files  : Yes"
    warn "  Override data/config : No  (existing data preserved)"
  fi

  if $TTY_AVAILABLE; then
    echo ""
    echo -e "  ${BOLD}Question 1 of 2 — System files${RESET}"
    echo -e "  This covers: app code, templates, static assets, scripts, requirements.txt"
    echo -e "  Your data/ directory is never touched by a code update."
    echo ""

    while true; do
      read -rp "  Update system files? [Y/n]: " _yn </dev/tty
      case "${_yn:-Y}" in
        [Yy]*|"") OVERRIDE_CODE=true;  break ;;
        [Nn]*)     OVERRIDE_CODE=false; break ;;
        *) echo "  Please enter Y or N." ;;
      esac
    done

    echo ""
    echo -e "  ${BOLD}Question 2 of 2 — Data and configuration${RESET}"
    echo -e "  This covers: ${RED}${BOLD}ALL${RESET} content in data/ — interests, resources, reports,"
    echo -e "  users, API keys, SMTP settings, and all other configuration."
    echo ""
    echo -e "  ${RED}⚠  Choosing Yes permanently deletes all existing data. This cannot be undone.${RESET}"
    echo -e "     Export a full backup from the Admin panel before proceeding."
    echo ""

    while true; do
      read -rp "  Override data and configuration files? [y/N]: " _yn </dev/tty
      case "${_yn:-N}" in
        [Yy]*)    OVERRIDE_DATA=true;  break ;;
        [Nn]*|"") OVERRIDE_DATA=false; break ;;
        *) echo "  Please enter Y or N." ;;
      esac
    done
  fi

  echo ""
  echo -e "  ${BOLD}Proceeding with:${RESET}"
  if $OVERRIDE_CODE; then
    echo -e "    Update system files  :  ${GREEN}Yes${RESET}"
  else
    echo -e "    Update system files  :  ${YELLOW}No — code left unchanged${RESET}"
  fi
  if $OVERRIDE_DATA; then
    echo -e "    Override data/config :  ${RED}Yes — all existing data will be erased${RESET}"
  else
    echo -e "    Override data/config :  ${GREEN}No — existing data preserved${RESET}"
  fi
  echo ""
  sleep 2
fi

# ── Step 1 — Python ───────────────────────────────────────────────────────────
banner "Step 1 of 6 — Checking Python"
echo ""
info "Searching for Python 3.10 or newer on this system…"

PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3; do
  if command -v "$cmd" &>/dev/null; then
    if "$cmd" -c 'import sys; exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      VER=$("$cmd" --version 2>&1)
      PYTHON="$cmd"
      ok "Found suitable Python: $VER  ($cmd)"
      break
    else
      VER=$("$cmd" --version 2>&1)
      warn "Found $VER — too old (Citadel requires 3.10+), will try to install a newer version"
    fi
  fi
done

if [[ -z "$PYTHON" ]]; then
  info "No suitable Python found — attempting to install Python 3.11 automatically…"
  echo ""

  if command -v apt-get &>/dev/null; then
    info "Detected apt (Debian / Ubuntu)"
    apt-get update -qq
    apt-get install -y python3.11 python3.11-venv \
      || die "apt-get failed to install Python 3.11.\n  Try manually: apt-get install python3.11 python3.11-venv"
    PYTHON="python3.11"

  elif command -v dnf &>/dev/null; then
    info "Detected dnf (RHEL / Fedora / Rocky / Alma)"
    dnf install -y python3.11 \
      || die "dnf failed to install Python 3.11.\n  Try manually: dnf install python3.11"
    PYTHON="python3.11"

  elif command -v yum &>/dev/null; then
    info "Detected yum (older RHEL / CentOS)"
    yum install -y python3.11 \
      || die "yum failed to install Python 3.11.\n  Try manually: yum install python3.11"
    PYTHON="python3.11"

  elif command -v pacman &>/dev/null; then
    info "Detected pacman (Arch Linux)"
    pacman -Sy --noconfirm python \
      || die "pacman failed to install Python.\n  Try manually: pacman -S python"
    PYTHON="python3"

  elif command -v zypper &>/dev/null; then
    info "Detected zypper (openSUSE)"
    zypper install -y python311 \
      || die "zypper failed to install Python 3.11.\n  Try manually: zypper install python311"
    PYTHON="python3.11"

  else
    die "Could not find a supported package manager (apt, dnf, yum, pacman, zypper).\n\n  Please install Python 3.10 or newer manually, then re-run this installer.\n\n  Download from: https://www.python.org/downloads/"
  fi

  if "$PYTHON" -c 'import sys; exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    VER=$("$PYTHON" --version 2>&1)
    ok "Python installed and verified: $VER"
  else
    die "Python was installed but still does not meet the 3.10+ requirement.\n  Installed version: $($PYTHON --version 2>&1)\n  Please install Python 3.11 or newer manually."
  fi
fi

# ── Step 2 — System user ─────────────────────────────────────────────────────
banner "Step 2 of 6 — Creating dedicated service user"
echo ""
info "Citadel runs as an unprivileged system user for security."
info "The user '${SERVICE_USER}' will own all application files and the running process."
echo ""

if id "$SERVICE_USER" &>/dev/null; then
  ok "System user '${SERVICE_USER}' already exists — skipping creation"
else
  useradd --system --shell /usr/sbin/nologin --create-home \
          --home-dir "$INSTALL_DIR" "$SERVICE_USER"
  ok "Created system user '${SERVICE_USER}' (no login shell, no password)"
fi

# Allow the service user to restart/stop/start its own service without a password
# so the web-based self-update feature can trigger a service restart automatically.
SYSTEMCTL_PATH=$(command -v systemctl 2>/dev/null || true)
if [[ -n "$SYSTEMCTL_PATH" ]]; then
  SUDOERS_FILE="/etc/sudoers.d/${SERVICE_NAME}"
  cat > "$SUDOERS_FILE" <<EOF
${SERVICE_USER} ALL=(ALL) NOPASSWD: ${SYSTEMCTL_PATH} restart ${SERVICE_NAME}, ${SYSTEMCTL_PATH} start ${SERVICE_NAME}, ${SYSTEMCTL_PATH} stop ${SERVICE_NAME}
EOF
  chmod 440 "$SUDOERS_FILE"
  ok "Sudoers entry written → ${SUDOERS_FILE} (service can self-restart for web updates)"
fi

# ── Step 3 — Install files ────────────────────────────────────────────────────
banner "Step 3 of 6 — Installing application files"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# install.sh lives inside deploy/ — the app root is one level up
APP_ROOT="$(dirname "$SCRIPT_DIR")"
SERVICE_STOPPED=false

# ── Code files ────────────────────────────────────────────────────────────────
if $EXISTING_INSTALL && ! $OVERRIDE_CODE; then
  info "Code update skipped — system files left unchanged."
else
  # Stop service cleanly before replacing files
  if $EXISTING_INSTALL && $SERVICE_WAS_RUNNING; then
    info "Stopping '${SERVICE_NAME}' for code update…"
    systemctl stop "$SERVICE_NAME" || true
    SERVICE_STOPPED=true
    sleep 1
  fi

  info "Source      : ${APP_ROOT}"
  info "Destination : ${INSTALL_DIR}"
  echo ""
  info "Copying application code, templates, and static assets…"
  info "(data/, logs/, .venv/, and build artifacts are excluded.)"
  echo ""

  mkdir -p "$INSTALL_DIR"

  rsync -a --delete --force \
    --exclude='data/' \
    --exclude='logs/' \
    --exclude='.venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='.git/' \
    --exclude='.claude/' \
    --exclude='.citadel.pid' \
    --exclude='deploy/install.sh' \
    --exclude='deploy/build_package.sh' \
    --exclude='deploy/nxcitadel-*.tar.gz' \
    "$APP_ROOT/" "$INSTALL_DIR/"

  ok "Application files installed to ${INSTALL_DIR}"
fi

# ── Data directories ──────────────────────────────────────────────────────────
if $OVERRIDE_DATA; then
  echo ""
  warn "Removing existing data/ directory as requested…"
  rm -rf "$INSTALL_DIR/data"
  mkdir -p \
    "$INSTALL_DIR/data/config" \
    "$INSTALL_DIR/data/users" \
    "$INSTALL_DIR/data/interests" \
    "$INSTALL_DIR/data/resources" \
    "$INSTALL_DIR/data/reports" \
    "$INSTALL_DIR/data/summary_reports" \
    "$INSTALL_DIR/data/iocs" \
    "$INSTALL_DIR/logs/archive"
  ok "Data directories wiped and recreated (empty)"
elif $EXISTING_INSTALL; then
  # Only ensure directories exist — never touch existing content
  mkdir -p \
    "$INSTALL_DIR/data/config" \
    "$INSTALL_DIR/data/users" \
    "$INSTALL_DIR/data/interests" \
    "$INSTALL_DIR/data/resources" \
    "$INSTALL_DIR/data/reports" \
    "$INSTALL_DIR/data/summary_reports" \
    "$INSTALL_DIR/data/iocs" \
    "$INSTALL_DIR/logs/archive"
  ok "Existing data and configuration preserved"
else
  mkdir -p \
    "$INSTALL_DIR/data/config" \
    "$INSTALL_DIR/data/users" \
    "$INSTALL_DIR/data/interests" \
    "$INSTALL_DIR/data/resources" \
    "$INSTALL_DIR/data/reports" \
    "$INSTALL_DIR/data/summary_reports" \
    "$INSTALL_DIR/data/iocs" \
    "$INSTALL_DIR/logs/archive"
  ok "Runtime data directories created (empty)"
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
ok "File ownership set to '${SERVICE_USER}'"

# ── Step 4 — Python virtualenv + dependencies ─────────────────────────────────
banner "Step 4 of 6 — Installing Python dependencies"
echo ""

VENV="$INSTALL_DIR/.venv"

if $EXISTING_INSTALL && ! $OVERRIDE_CODE; then
  info "Code update skipped — Python environment unchanged."
else
  info "Creating / updating isolated Python virtual environment in ${VENV}"
  echo ""

  "$PYTHON" -m venv "$VENV"
  ok "Virtual environment ready"

  echo ""
  info "Installing / upgrading packages from requirements.txt…"
  info "Packages include: FastAPI, uvicorn, APScheduler, Anthropic SDK, bcrypt, pyotp, and more."
  echo ""

  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet --upgrade -r "$INSTALL_DIR/requirements.txt"

  chown -R "$SERVICE_USER:$SERVICE_USER" "$VENV"
  ok "All Python dependencies installed"
fi

# ── Step 5 — Systemd service ──────────────────────────────────────────────────
banner "Step 5 of 6 — Configuring systemd service"
echo ""
info "Writing ${SERVICE_NAME}.service to /etc/systemd/system/"
info "The service is set to start automatically on every system boot."
echo ""

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Nx-Citadel Intelligence Monitor
Documentation=https://github.com/your-org/nxcitadel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${VENV}/bin/python run.py
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Patch port into run.py if non-default
if [[ "$APP_PORT" != "8000" ]]; then
  sed -i "s/port=8000/port=${APP_PORT}/" "$INSTALL_DIR/run.py"
  info "Port set to ${APP_PORT} in run.py"
fi

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
ok "Systemd unit file written to ${SERVICE_FILE}"
ok "Service enabled — Citadel will start automatically on boot"

# ── Step 6 — Start / restart service ─────────────────────────────────────────
banner "Step 6 of 6 — Starting Nx-Citadel"
echo ""

if $EXISTING_INSTALL && ! $SERVICE_STOPPED; then
  # Upgrade path where code was NOT changed — service was never stopped
  info "System files were not updated — service restart not required."
  if $SERVICE_WAS_RUNNING; then
    ok "Service '${SERVICE_NAME}' continues running unchanged."
  else
    info "Service was already stopped. Starting now…"
    systemctl start "$SERVICE_NAME"
    sleep 3
  fi
elif $EXISTING_INSTALL && $SERVICE_STOPPED; then
  info "Restarting '${SERVICE_NAME}' after code update…"
  systemctl start "$SERVICE_NAME"
  sleep 4
else
  info "Starting the ${SERVICE_NAME} service now…"
  info "On first start, Citadel will create the default admin account automatically."
  echo ""
  systemctl start "$SERVICE_NAME"
  sleep 4
fi

if systemctl is-active --quiet "$SERVICE_NAME"; then
  ok "Service is running  ($(systemctl is-active ${SERVICE_NAME}))"
else
  warn "The service may not have started cleanly."
  warn "Check the logs with:  journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
  echo ""
  warn "Common causes: port ${APP_PORT} already in use, or a Python import error."
  warn "The install itself succeeded — fix the issue and run: sudo systemctl start ${SERVICE_NAME}"
fi

# ── Detect IP for final output ────────────────────────────────────────────────
HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[[ -z "$HOST_IP" ]] && HOST_IP="<your-server-ip>"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
if $EXISTING_INSTALL; then
  echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════════════${RESET}"
  echo -e "${GREEN}${BOLD}  Nx-Citadel updated successfully!${RESET}"
  echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════════════${RESET}"
else
  echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════════════${RESET}"
  echo -e "${GREEN}${BOLD}  Nx-Citadel installed and running!${RESET}"
  echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════════════${RESET}"
fi
echo ""
echo -e "  ${BOLD}Open in your browser:${RESET}"
echo -e "    ${CYAN}http://localhost:${APP_PORT}${RESET}  (from this machine)"
if [[ "$HOST_IP" != "<your-server-ip>" ]]; then
  echo -e "    ${CYAN}http://${HOST_IP}:${APP_PORT}${RESET}  (from the network)"
fi
echo ""

# Only show default credentials on a fresh install or after data wipe
if ! $EXISTING_INSTALL || $OVERRIDE_DATA; then
  echo -e "  ${BOLD}━━━  Default administrator account  ━━━${RESET}"
  echo ""
  echo -e "    Username : ${YELLOW}${BOLD}admin${RESET}"
  echo -e "    Password : ${YELLOW}${BOLD}admin${RESET}"
  echo ""
  echo -e "  ${RED}${BOLD}  ⚠  SECURITY — complete these steps before exposing to a network:${RESET}"
  echo ""
  echo -e "    1. Log in with admin / admin"
  echo -e "    2. Go to ${BOLD}Account settings → Change password${RESET}"
  echo -e "       Set a strong, unique password for the admin account"
  echo -e "    3. Go to ${BOLD}Account settings → Two-Factor Authentication${RESET}"
  echo -e "       Scan the QR code with an authenticator app"
  echo -e "       Enter the 6-digit code to confirm and enable MFA"
  echo ""
fi

if ! $EXISTING_INSTALL; then
  echo -e "  ${BOLD}━━━  First-time configuration checklist  ━━━${RESET}"
  echo ""
  echo -e "    After logging in, go to ${BOLD}Settings${RESET} in the side menu to configure:"
  echo ""
  echo -e "    □ ${BOLD}LLM / AI${RESET}    — Enter your Anthropic API key"
  echo -e "                   Choose the Claude model (default: claude-sonnet-4-6)"
  echo ""
  echo -e "    □ ${BOLD}Search${RESET}      — DuckDuckGo works with no API key (default)"
  echo -e "                   Optionally switch to SerpAPI or Brave Search"
  echo ""
  echo -e "    □ ${BOLD}Email${RESET}       — SMTP details for report delivery"
  echo ""
  echo -e "    □ ${BOLD}Slack / Discord${RESET} — Webhook URLs for channel delivery"
  echo ""
  echo -e "    □ ${BOLD}SMS${RESET}         — Twilio account SID + auth token + from-number"
  echo ""
  echo -e "    Then go to ${BOLD}Interests${RESET} to create your first monitoring topic."
  echo ""

  echo -e "  ${BOLD}━━━  Creating additional users  ━━━${RESET}"
  echo ""
  echo -e "    Go to ${BOLD}Admin → Users${RESET} to create accounts for other people."
  echo -e "    Roles available:"
  echo -e "      • ${BOLD}user${RESET}    — can view reports for their assigned interests"
  echo -e "      • ${BOLD}manager${RESET} — can manage interests and resources"
  echo -e "      • ${BOLD}admin${RESET}   — full access including user management"
  echo ""
  echo -e "    Managers and admins are prompted to set up MFA on first login."
  echo ""
fi

echo -e "  ${BOLD}━━━  Service management commands  ━━━${RESET}"
echo ""
echo -e "    Check status  : sudo systemctl status ${SERVICE_NAME}"
echo -e "    View logs     : sudo journalctl -u ${SERVICE_NAME} -f"
echo -e "    Restart       : sudo systemctl restart ${SERVICE_NAME}"
echo -e "    Stop          : sudo systemctl stop ${SERVICE_NAME}"
echo -e "    Disable boot  : sudo systemctl disable ${SERVICE_NAME}"
echo ""
echo -e "    Uninstall (removes all data!):"
echo -e "    sudo systemctl disable --now ${SERVICE_NAME} && \\"
echo -e "    sudo rm -rf ${INSTALL_DIR} /etc/systemd/system/${SERVICE_NAME}.service && \\"
echo -e "    sudo systemctl daemon-reload"
echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════════════${RESET}"
echo ""
