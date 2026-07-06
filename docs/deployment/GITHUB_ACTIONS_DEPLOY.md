# GitHub Actions Lightsail Deployment

This workflow deploys Garner Quant to the AWS Lightsail server whenever `main`
is pushed. It updates code only; it does not edit runtime state files directly.

## GitHub Secrets

Add these repository secrets in GitHub:

- `AWS_HOST`: `18.133.222.149`
- `AWS_USER`: `ubuntu`
- `AWS_SSH_PRIVATE_KEY`: private SSH key allowed to log in as `ubuntu`

Do not commit SSH keys, `.env`, dashboard passwords, Supabase keys, or Telegram
tokens to the repository.

## Lightsail Server Setup

The workflow assumes:

- repo path: `/home/ubuntu/garner-quant`
- dashboard service: `garner-quant-dashboard`
- runtime service: `garner-quant-runtime`
- virtual environment: `/home/ubuntu/garner-quant/.venv`
- dashboard command in systemd: Streamlit `web_dashboard.py` on port `8501`
- runtime command in systemd: `python runtime/live_runtime.py`

On the server, confirm the repository already has `origin` pointing at GitHub:

```bash
cd /home/ubuntu/garner-quant
git remote -v
```

Confirm both services exist:

```bash
sudo systemctl status garner-quant-dashboard --no-pager
sudo systemctl status garner-quant-runtime --no-pager
```

The server `.env` file should remain on the server and should contain production
secrets such as:

```bash
DASHBOARD_PASSWORD=...
DASHBOARD_AUTH_SECRET=...
DASHBOARD_SESSION_DAYS=7
ENVIRONMENT=production
SUPABASE_URL=...
SUPABASE_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

## Workflow Behaviour

`.github/workflows/deploy.yml` runs on:

- push to `main`
- manual `workflow_dispatch`

Remote deploy order:

1. SSH to Lightsail using GitHub secrets.
2. `cd /home/ubuntu/garner-quant`.
3. Stop `garner-quant-runtime` before updating code.
4. `git fetch origin main`.
5. `git reset --hard origin/main`.
6. Create `.venv` if missing.
7. Upgrade pip and install `requirements.txt`.
8. Run `python -m runtime.startup_validation`.
9. If validation passes, restart dashboard and runtime.
10. If validation fails, leave runtime stopped and exit failed.
11. Print dashboard and runtime service status.

The runtime is intentionally stopped before pulling so it cannot write while the
working tree is being updated.

## Manual Deploy Fallback

Run this from your local machine if GitHub Actions is unavailable:

```bash
ssh ubuntu@18.133.222.149 <<'REMOTE_DEPLOY'
set -euo pipefail

APP_DIR="/home/ubuntu/garner-quant"
DASHBOARD_SERVICE="garner-quant-dashboard"
RUNTIME_SERVICE="garner-quant-runtime"

cd "$APP_DIR"

sudo systemctl stop "$RUNTIME_SERVICE" || true

git fetch origin main
git reset --hard origin/main

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

if ! .venv/bin/python -m runtime.startup_validation; then
  echo "Startup validation failed. Runtime remains stopped."
  sudo systemctl status "$DASHBOARD_SERVICE" --no-pager || true
  sudo systemctl status "$RUNTIME_SERVICE" --no-pager || true
  exit 1
fi

sudo systemctl restart "$DASHBOARD_SERVICE"
sudo systemctl restart "$RUNTIME_SERVICE"

sudo systemctl status "$DASHBOARD_SERVICE" --no-pager
sudo systemctl status "$RUNTIME_SERVICE" --no-pager
REMOTE_DEPLOY
```

If validation fails, inspect the server logs before restarting runtime:

```bash
journalctl -u garner-quant-dashboard -n 100 --no-pager
journalctl -u garner-quant-runtime -n 100 --no-pager
```
