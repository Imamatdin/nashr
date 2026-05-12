# Nashr Deployment Guide

Production deployment of Nashr on a single Hetzner VPS, with Supabase
(managed Postgres) and Cloudflare R2 (object storage) as external SaaS.
This guide assumes you have shell access to the VPS and the Cloudflare
+ Supabase + Telegram credentials in hand.

## Prerequisites

- A Hetzner Cloud VPS — **CX21** (2 vCPU, 4 GB RAM, 40 GB disk) is the
  minimum; CCX13 (4 vCPU AMD, 16 GB RAM) is comfortable for production.
- A domain name (e.g. `nashr.uz`) with DNS access.
- Supabase project (free tier is sufficient for MVP).
- Cloudflare account with R2 enabled.
- Telegram bot token from [@BotFather](https://t.me/BotFather).
- Anthropic API key and Google Gemini API key.

## Step 1 — Supabase

1. Create a new project at <https://supabase.com>.
2. Project Settings → API. Copy the **URL** and the **service_role** key.
3. Apply the migrations from your local checkout:

   ```bash
   supabase db push --db-url "postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres"
   ```

   Or paste the SQL manually in the Supabase SQL editor:

   - `supabase/migrations/001_initial_schema.sql`
   - `supabase/migrations/002_platform_additions.sql`

## Step 2 — Cloudflare R2

1. Cloudflare Dashboard → R2 → **Create bucket**, name it `nashr-files`.
2. Manage R2 API Tokens → **Create API token** (Object Read & Write,
   scoped to the new bucket).
3. Note: Account ID, Access Key ID, Secret Access Key.
4. Endpoint URL is `https://<account-id>.r2.cloudflarestorage.com`.

## Step 3 — Hetzner VPS

1. Create a CX21 server running Ubuntu 24.04 LTS.
2. SSH in (`ssh root@<ip>`) and install Docker:

   ```bash
   curl -fsSL https://get.docker.com | sh
   usermod -aG docker $USER
   apt-get install -y docker-compose-plugin
   ```

3. Re-login so the group change takes effect.
4. Clone the repository:

   ```bash
   git clone https://github.com/Imamatdin/nashr.git
   cd nashr
   ```

5. Copy and edit `.env`:

   ```bash
   cp .env.example .env
   nano .env   # fill every value from steps 1–2 plus your API keys
   ```

## Step 4 — Domain + automatic HTTPS via Caddy

1. Point an `A` record for your domain at the Hetzner VPS IP.
2. Install Caddy on the host (TLS is far simpler than running it inside
   compose because Caddy auto-renews certs out of the box):

   ```bash
   apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
       | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
       | tee /etc/apt/sources.list.d/caddy-stable.list
   apt-get update && apt-get install -y caddy
   ```

3. Edit `/etc/caddy/Caddyfile`:

   ```
   nashr.uz {
       reverse_proxy localhost:8080
   }
   ```

4. Reload Caddy:

   ```bash
   systemctl reload caddy
   ```

## Step 5 — Set the Telegram webhook

```bash
TOKEN="<your-bot-token>"
DOMAIN="nashr.uz"
curl "https://api.telegram.org/bot${TOKEN}/setWebhook?url=https://${DOMAIN}/webhook"
```

You should see `{"ok":true,"result":true,"description":"Webhook was set"}`.

## Step 6 — Boot the stack

```bash
docker compose up -d --build
```

The first build takes ~10 minutes (Playwright fetches Chromium, the
Node renderer compiles, Tesseract language packs install).

## Step 7 — Verify

```bash
# Health
curl https://nashr.uz/health
# → {"status":"ok","service":"nashr-bot","version":"1.0.0"}

# Logs
docker compose logs -f bot

# Telegram smoke test: send /start to your bot
```

## Maintenance

```bash
# Update
git pull
docker compose up -d --build

# Tail logs
docker compose logs -f bot

# Restart only the bot
docker compose restart bot

# Tear everything down (containers and volumes stay)
docker compose down

# Re-set the webhook after a domain change
curl "https://api.telegram.org/bot${TOKEN}/setWebhook?url=https://${DOMAIN}/webhook"

# Inspect the current webhook
curl "https://api.telegram.org/bot${TOKEN}/getWebhookInfo"
```

## Troubleshooting

**Bot starts but doesn't receive updates.**
Re-set the webhook (Step 5). Confirm `/health` is reachable over HTTPS;
Telegram refuses self-signed certs.

**Health endpoint returns 502 from Caddy.**
The container is not listening on `:8080`. Check `docker compose logs
bot` for tracebacks — most often a missing env var (`TELEGRAM_BOT_TOKEN`,
`SUPABASE_URL`, `ANTHROPIC_API_KEY`).

**Presentation rendering fails with `playwright: command not found`.**
The Playwright install layer in the Dockerfile didn't complete. Rebuild
with `docker compose build --no-cache bot`.

**R2 uploads silently fail.**
Check `R2_ENDPOINT` is the full S3 URL including `https://`. The
`FileStorage` client logs `storage_upload` lines per success and
`R2 not configured` once at boot when credentials are absent.
