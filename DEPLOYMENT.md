# Garner Quant Deployment

Garner Quant can run 24/5 on an always-on VPS so the Streamlit dashboard remains reachable from your phone while the live runtime refreshes status in the background.

This deployment keeps the project in paper-only monitoring by default. Do not enable `paper_execution` until it has been deliberately tested on the server.

## Requirements

- Python 3.10 or newer
- A Linux VPS or always-on server
- Firewall access to dashboard port `8501`
- Project files copied to the server, for example `/opt/garner-quant`
- Environment variables stored in `.env`, never hardcoded in source

## Environment Variables

Create `.env` from `.env.example` and fill in only the services you use:

```bash
cp .env.example .env
nano .env
```

Expected variables:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `EMAIL_SMTP_HOST`
- `EMAIL_SMTP_PORT`
- `EMAIL_USERNAME`
- `EMAIL_PASSWORD`
- `EMAIL_FROM`
- `EMAIL_TO`

Keep `.env` private. It is ignored by git.

## Install

From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Confirm the safe runtime defaults before starting:

```bash
cat runtime/live_runtime_config.json
```

The default deployment-safe values are:

```json
"mode": "monitor_only",
"paper_execution_enabled": false
```

## Run Locally

Windows PowerShell:

```powershell
.\scripts\start_dashboard.ps1
.\scripts\start_runtime.ps1
```

Linux:

```bash
./scripts/start_dashboard.sh
./scripts/start_runtime.sh
```

Dashboard command:

```bash
python -m streamlit run web_dashboard.py --server.address 0.0.0.0 --server.port 8501
```

Runtime command:

```bash
python runtime/live_runtime.py
```

## Run Continuously On A VPS

The `deploy/` directory contains systemd service templates:

- `deploy/garner-quant-dashboard.service`
- `deploy/garner-quant-runtime.service`

Copy them into systemd:

```bash
sudo cp deploy/garner-quant-dashboard.service /etc/systemd/system/
sudo cp deploy/garner-quant-runtime.service /etc/systemd/system/
sudo systemctl daemon-reload
```

Enable and start both services:

```bash
sudo systemctl enable --now garner-quant-dashboard
sudo systemctl enable --now garner-quant-runtime
```

The templates assume:

- Project path: `/opt/garner-quant`
- Virtual environment: `/opt/garner-quant/.venv`
- Environment file: `/opt/garner-quant/.env`

Change those paths in the service files if your server uses a different directory.

## Stop And Restart

```bash
sudo systemctl stop garner-quant-dashboard
sudo systemctl stop garner-quant-runtime
sudo systemctl restart garner-quant-dashboard
sudo systemctl restart garner-quant-runtime
sudo systemctl status garner-quant-dashboard
sudo systemctl status garner-quant-runtime
```

Both services use:

```ini
Restart=always
RestartSec=10
```

so systemd will restart them automatically after failures.

## Logs And Health

Dashboard logs:

```bash
journalctl -u garner-quant-dashboard -f
```

Runtime logs:

```bash
journalctl -u garner-quant-runtime -f
```

Runtime health check:

```bash
python runtime/health_check.py
```

The health check reads `data/live_runtime_status.json` and exits with:

- `0` when runtime status is healthy
- `1` when the runtime is stale, stopped, missing, or reporting an error

Default stale heartbeat threshold: 10 minutes.

Expected runtime files:

- `data/live_runtime_status.json`
- `data/runtime_operations_log.json`
- `data/live_monitor_snapshot.json`

Systemd journal logs are the primary logs for long-running services.

## View From iPhone

Open the dashboard from Safari using:

```text
http://SERVER_IP:8501
```

For a public VPS, restrict access with firewall rules, a VPN, reverse proxy authentication, or another access-control layer before leaving the dashboard exposed to the internet.

## Known Limitations

- The dashboard displays runtime state but does not start or stop processes.
- The server must remain online for 24/5 operation.
- Market data availability depends on the configured data providers.
- Default deployment is monitor-only. Paper execution must be enabled deliberately in `runtime/live_runtime_config.json` after testing.
