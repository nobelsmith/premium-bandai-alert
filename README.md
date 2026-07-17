# Premium Bandai Discord Alert

Monitors Premium Bandai USA (One Piece + BANDAI CARD SHOP) for **new products** and **availability changes**, then posts Discord webhook embeds.

**Primary runtime:** Vultr (or any Linux VPS) via a systemd timer every **2 minutes**.  
GitHub Actions remains available for optional manual runs only (cron disabled — unreliable).

## How it works

1. Polls `https://p-bandai.com/api/search` (HTML fallback) with shop `05-0004` and series `03-002`.
2. Diffs against a persisted `state.json` snapshot.
3. Alerts on:
   - **New product** — unseen `productCode`
   - **Became available** — `saleStatus == On` and not `OUT_OF_STOCK` / `PRE_ORDER_CLOSED`
4. First successful run **seeds** the baseline and does not spam historical listings.

## Vultr / VPS setup (recommended)

On the server (Ubuntu/Debian):

```bash
# as a user with sudo
sudo apt update && sudo apt install -y git python3 python3-venv rsync

git clone git@github.com:nobelsmith/premium-bandai-alert.git
cd premium-bandai-alert
cp .env.example .env
nano .env   # set DISCORD_WEBHOOK_URL

chmod +x deploy/install-systemd.sh
sudo bash deploy/install-systemd.sh
```

That installs to `/opt/premium-bandai-alert`, creates a venv, and enables `pbandai-monitor.timer` (every 2 minutes).

Useful commands:

```bash
systemctl status pbandai-monitor.timer
systemctl list-timers pbandai-monitor.timer
journalctl -u pbandai-monitor.service -n 50 --no-pager
sudo systemctl start pbandai-monitor.service   # run once now
```

To change the interval, edit `OnUnitActiveSec` in [`deploy/pbandai-monitor.timer`](deploy/pbandai-monitor.timer), then re-run the install script (or `sudo systemctl daemon-reload && sudo systemctl restart pbandai-monitor.timer`).

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set DISCORD_WEBHOOK_URL
set -a && source .env && set +a
python monitor.py
```

`state.json` is written next to the script (gitignored). Delete it to re-seed.

## Discord webhook

1. Discord channel → **Edit Channel** → **Integrations** → **Webhooks** → **New Webhook**
2. Copy the webhook URL into `.env` as `DISCORD_WEBHOOK_URL` on the VPS

## Optional: GitHub Actions manual run

Push is not required for Vultr. The workflow only has **Run workflow** (no schedule). If you use it, add repository secret `DISCORD_WEBHOOK_URL`. Do **not** run both GHA and Vultr against the same Discord channel unless you accept duplicate alerts (they keep separate state).

## Optional env vars

| Variable | Default | Meaning |
| --- | --- | --- |
| `DISCORD_WEBHOOK_URL` | *(required)* | Discord incoming webhook |
| `BANDAI_SHOP` | `05-0004` | Shop filter (BANDAI CARD SHOP) |
| `BANDAI_SERIES` | `03-002` | Series filter (ONE PIECE) |
| `BANDAI_AREA` | `US` | `X-G1-Area-Code` header |
| `BANDAI_PAGE_LIMIT` | `100` | Page size for pagination |
| `STATE_PATH` | `state.json` | Snapshot file path |
