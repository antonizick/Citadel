#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  Nx-Citadel — Stop
#  Handles: systemd service, StartCitadel.sh PID file, or any stray process
#  Usage: bash StopCitadel.sh
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/.citadel.pid"
PORT=9123
SERVICE_NAME="citadel"   # systemd unit name (citadel.service)

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "  ${GREEN}✔${RESET}  $1"; }
info() { echo -e "  ${CYAN}→${RESET}  $1"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
die()  { echo -e "\n${RED}${BOLD}ERROR:${RESET} $1\n"; exit 1; }

echo ""
echo -e "${CYAN}${BOLD}Nx-Citadel — Stopping services${RESET}"
echo ""

stopped_something=0

# ── 1. Stop systemd service if it is active ──────────────────────────────────
if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
  info "Systemd service '${SERVICE_NAME}' is active — stopping it…"
  if sudo systemctl stop "${SERVICE_NAME}" 2>/dev/null; then
    ok "Systemd service stopped."
    stopped_something=1
  else
    warn "Could not stop systemd service (sudo required). Trying process methods…"
  fi
elif systemctl is-active --quiet "nxcitadel" 2>/dev/null; then
  # Also try the alternate service name
  info "Systemd service 'nxcitadel' is active — stopping it…"
  if sudo systemctl stop "nxcitadel" 2>/dev/null; then
    ok "Systemd service stopped."
    stopped_something=1
  else
    warn "Could not stop systemd service (sudo required). Trying process methods…"
  fi
fi

# ── 2. Kill PID from our own PID file ────────────────────────────────────────
if [[ -f "$PID_FILE" ]]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    info "Stopping PID-file process (PID: ${PID})…"
    kill "$PID" 2>/dev/null || true
    for i in {1..10}; do
      sleep 1
      kill -0 "$PID" 2>/dev/null || break
    done
    if kill -0 "$PID" 2>/dev/null; then
      warn "Process did not exit cleanly — sending SIGKILL…"
      kill -9 "$PID" 2>/dev/null || true
      sleep 1
    fi
    if ! kill -0 "$PID" 2>/dev/null; then
      ok "PID-file process stopped."
      stopped_something=1
    else
      warn "Could not kill PID ${PID}."
    fi
  fi
  rm -f "$PID_FILE"
fi

# ── 3. Kill any remaining run.py / uvicorn processes for this project ─────────
#    Matches only processes whose cmdline contains this project's own directory
#    path, so other uvicorn/run.py servers on the box (e.g. Lucent's voice box)
#    are never touched.
mapfile -t STRAY_PIDS < <(
  pgrep -f "run\.py" 2>/dev/null || true
)
mapfile -t UVICORN_PIDS < <(
  pgrep -f "uvicorn.*app\.main" 2>/dev/null || true
)
ALL_PIDS=("${STRAY_PIDS[@]:-}" "${UVICORN_PIDS[@]:-}")

for PID in "${ALL_PIDS[@]}"; do
  [[ -z "$PID" ]] && continue
  # Skip our own shell process
  [[ "$PID" == "$$" ]] && continue
  if kill -0 "$PID" 2>/dev/null; then
    CWD=$(readlink "/proc/${PID}/cwd" 2>/dev/null || true)
    CMDLINE=$(cat "/proc/${PID}/cmdline" 2>/dev/null | tr '\0' ' ' || true)
    # Only kill if the process's cwd or cmdline is under this project's directory
    if [[ "$CWD" == "$SCRIPT_DIR"* ]] || echo "$CMDLINE" | grep -qF "$SCRIPT_DIR"; then
      info "Killing stray process (PID: ${PID}): ${CMDLINE:0:80}…"
      kill "$PID" 2>/dev/null || true
      sleep 2
      kill -0 "$PID" 2>/dev/null && kill -9 "$PID" 2>/dev/null || true
      ok "Process ${PID} stopped."
      stopped_something=1
    fi
  fi
done

# ── 4. Final check — anything still bound to port 8000? ──────────────────────
if command -v ss &>/dev/null; then
  PORT_PIDS=$(ss -tlnp "sport = :${PORT}" 2>/dev/null | grep -oP 'pid=\K[0-9]+' || true)
elif command -v lsof &>/dev/null; then
  PORT_PIDS=$(lsof -ti tcp:"${PORT}" 2>/dev/null || true)
else
  PORT_PIDS=""
fi

for PID in $PORT_PIDS; do
  [[ -z "$PID" ]] && continue
  if kill -0 "$PID" 2>/dev/null; then
    CMDLINE=$(cat "/proc/${PID}/cmdline" 2>/dev/null | tr '\0' ' ' || echo "unknown")
    warn "Port ${PORT} still held by PID ${PID} (${CMDLINE:0:60}) — killing…"
    kill "$PID" 2>/dev/null || true
    sleep 2
    kill -0 "$PID" 2>/dev/null && kill -9 "$PID" 2>/dev/null || true
    ok "Process ${PID} killed."
    stopped_something=1
  fi
done

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
if [[ $stopped_something -eq 1 ]]; then
  ok "Citadel stopped successfully."
else
  info "No running Citadel process found — nothing to stop."
fi

echo ""
info "To start again: bash StartCitadel.sh"
echo ""
