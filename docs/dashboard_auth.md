# Dashboard Authentication

Garner Quant uses a lightweight shared password for Streamlit dashboard access.

## Local Streamlit Secrets

Create `.streamlit/secrets.toml`:

```toml
[dashboard]
password = "replace-with-shared-dashboard-password"
```

The local `secrets.toml` file is ignored by git.

## Environment Fallback

If Streamlit secrets are not available, set one of:

```powershell
$env:GARNER_QUANT_DASHBOARD_PASSWORD = "replace-with-shared-dashboard-password"
```

or:

```powershell
$env:DASHBOARD_PASSWORD = "replace-with-shared-dashboard-password"
```

## Rotation

To rotate the shared dashboard password, update `[dashboard].password` in
Streamlit secrets or update the environment variable, then restart Streamlit.
Existing authenticated sessions are invalidated because the session fingerprint
is tied to the configured password.

## Remember This Device

Session login is implemented now. Persistent signed-cookie login is intentionally
not enabled until a safe cookie component or first-party Streamlit support is
available in this deployment.
