# Premium Bandai Discord Alert

Monitors Premium Bandai USA (One Piece + BANDAI CARD SHOP) for **new products** and **availability changes**, then posts Discord webhook embeds.

## How it works

1. Polls `https://p-bandai.com/api/search` with shop `05-0004` and series `03-002` (no End-only filter).
2. Diffs against a persisted `state.json` snapshot.
3. Alerts on:
   - **New product** — unseen `productCode`
   - **Became available** — `saleStatus == On` and not `OUT_OF_STOCK` / `PRE_ORDER_CLOSED`
4. First successful run **seeds** the baseline and does not spam historical listings.

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

Or without `.env`:

```bash
export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'
python monitor.py
```

`state.json` is written next to the script (gitignored). Delete it to re-seed.

## Discord webhook

1. Discord channel → **Edit Channel** → **Integrations** → **Webhooks** → **New Webhook**
2. Copy the webhook URL
3. Store it as `DISCORD_WEBHOOK_URL` locally and as a GitHub Actions secret

## GitHub Actions

1. Push this repo to GitHub
2. **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `DISCORD_WEBHOOK_URL`
   - Value: your webhook URL
3. The workflow [`.github/workflows/monitor.yml`](.github/workflows/monitor.yml) runs every **5 minutes** and on manual **Run workflow**
4. `state.json` is restored/saved via Actions cache (keys prefixed `pbandai-state-v1-`)

First Actions run seeds the catalog silently. Later runs send alerts when something changes.

## Optional env vars

| Variable | Default | Meaning |
| --- | --- | --- |
| `DISCORD_WEBHOOK_URL` | *(required)* | Discord incoming webhook |
| `BANDAI_SHOP` | `05-0004` | Shop filter (BANDAI CARD SHOP) |
| `BANDAI_SERIES` | `03-002` | Series filter (ONE PIECE) |
| `BANDAI_AREA` | `US` | `X-G1-Area-Code` header |
| `BANDAI_PAGE_LIMIT` | `100` | Page size for pagination |
| `STATE_PATH` | `state.json` | Snapshot file path |
