# Premium Bandai Discord Alert

Monitors Premium Bandai USA (One Piece + BANDAI CARD SHOP) for **new products** and **availability changes**, then posts Discord webhook embeds.

**Primary runtime:** Vultr (or any Linux VPS) via a systemd timer every **2 minutes**.  
GitHub Actions remains available for optional manual runs only (cron disabled — unreliable).

Uses [uv](https://docs.astral.sh/uv/) for Python env + dependency management.

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
sudo apt update && sudo apt install -y git curl rsync
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"

git clone https://github.com/nobelsmith/premium-bandai-alert.git
cd premium-bandai-alert
cp .env.example .env
nano .env   # set DISCORD_WEBHOOK_URL

chmod +x deploy/install-systemd.sh
sudo bash deploy/install-systemd.sh
```

That installs to `/opt/premium-bandai-alert`, runs `uv sync`, and enables `pbandai-monitor.timer` (every 2 minutes).

Useful commands:

```bash
systemctl status pbandai-monitor.timer
systemctl list-timers pbandai-monitor.timer
journalctl -u pbandai-monitor.service -n 50 --no-pager
sudo systemctl start pbandai-monitor.service   # run once now
```

To change the interval, edit `OnCalendar` in [`deploy/pbandai-monitor.timer`](deploy/pbandai-monitor.timer), then re-run the install script (or `sudo systemctl daemon-reload && sudo systemctl restart pbandai-monitor.timer`).

## Local setup

```bash
# install uv if needed: https://docs.astral.sh/uv/getting-started/installation/
uv sync --group dev
cp .env.example .env
# Edit .env and set DISCORD_WEBHOOK_URL
set -a && source .env && set +a
uv run python monitor.py
```

`state.json` is written next to the script (gitignored). Delete it to re-seed.

## Testing

```bash
uv sync --group dev

# Unit tests only (offline, fixtures)
uv run pytest -m "not live"

# Full suite including live Bandai API/HTML contract checks
uv run pytest

# Live contract only — use this when you suspect the site changed
uv run pytest -m live -s
```

Live tests hit `p-bandai.com` and fail if response shape, `PRELOAD_DATA`, pagination, or required product fields change. CI runs unit + live tests on push/PR and weekly.

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
