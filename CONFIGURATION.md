# Garner Quant Configuration

## Telegram Notifications

Garner Quant reads Telegram credentials from environment variables:

```powershell
$env:TELEGRAM_BOT_TOKEN="your_bot_token"
$env:TELEGRAM_CHAT_ID="your_chat_id"
```

These values should never be hardcoded in Python files, committed to Git, or
stored in tracked configuration. For local development, use an ignored `.env`
file or set them in your shell/session. For Streamlit deployments, use
Streamlit secrets with the same names.

If Telegram credentials are missing, notification calls log:

```text
Telegram not configured.
```

and continue execution normally.

## Optional Email Notifications

Email notifications are optional. The unified notifier checks these environment
variables when email delivery is used:

```powershell
$env:EMAIL_SMTP_HOST="smtp.example.com"
$env:EMAIL_SMTP_PORT="587"
$env:EMAIL_USERNAME="your_email_username"
$env:EMAIL_PASSWORD="your_email_password"
$env:EMAIL_FROM="alerts@example.com"
$env:EMAIL_TO="recipient@example.com"
```

Compatible `SMTP_*` names are also supported for host, port, username, and
password.

Never commit email credentials to Git.
