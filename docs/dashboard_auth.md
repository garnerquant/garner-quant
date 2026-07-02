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

Session login is implemented now. The dashboard stays unlocked during normal
Streamlit reruns and page navigation, but closing the browser session may require
signing in again.

Persistent remember-device login is planned but not currently active, so the
login screen does not show a remember-device checkbox. Add it only after a safe
signed-cookie implementation is available for this deployment.
