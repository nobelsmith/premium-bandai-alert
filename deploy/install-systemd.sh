#!/usr/bin/env bash
# Install the monitor as a systemd timer on a Linux VPS (e.g. Vultr).
# Run as root from the repo root, or: sudo bash deploy/install-systemd.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${INSTALL_DIR:-/opt/premium-bandai-alert}"
SERVICE_USER="${SERVICE_USER:-root}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Re-run as root (sudo)." >&2
  exit 1
fi

if [[ ! -f "$REPO_ROOT/.env" ]]; then
  echo "Missing $REPO_ROOT/.env — copy .env.example and set DISCORD_WEBHOOK_URL first." >&2
  exit 1
fi

if ! grep -q '^DISCORD_WEBHOOK_URL=.\+' "$REPO_ROOT/.env"; then
  echo "DISCORD_WEBHOOK_URL is empty in .env" >&2
  exit 1
fi

echo "Installing to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'state.json' \
  --exclude '.DS_Store' \
  "$REPO_ROOT/" "$INSTALL_DIR/"

# Keep existing VPS state.json if present; otherwise start fresh (seed on first run).
if [[ -f "$REPO_ROOT/state.json" && ! -f "$INSTALL_DIR/state.json" ]]; then
  cp "$REPO_ROOT/state.json" "$INSTALL_DIR/state.json"
fi

chmod 600 "$INSTALL_DIR/.env"

python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

install -m 644 "$INSTALL_DIR/deploy/pbandai-monitor.service" /etc/systemd/system/pbandai-monitor.service
install -m 644 "$INSTALL_DIR/deploy/pbandai-monitor.timer" /etc/systemd/system/pbandai-monitor.timer

systemctl daemon-reload
systemctl enable --now pbandai-monitor.timer

echo
echo "Timer status:"
systemctl status pbandai-monitor.timer --no-pager || true
echo
echo "Next runs:"
systemctl list-timers pbandai-monitor.timer --no-pager || true
echo
echo "Run once now:"
systemctl start pbandai-monitor.service
echo "Last run log:"
journalctl -u pbandai-monitor.service -n 20 --no-pager || true
echo
echo "Done. Polls every 2 minutes via systemd."
