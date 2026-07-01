# Windows Local Server Mode

Use Windows local server mode when you want Garner Quant to start automatically whenever your Windows user logs in.

This starts:

- `GarnerQuantRuntime`: `python runtime/live_runtime.py`
- `GarnerQuantDashboard`: `python -m streamlit run web_dashboard.py --server.address 0.0.0.0 --server.port 8501`

No trading strategy, config, or portfolio files are changed by this setup.

## Install

Open PowerShell from the project root:

```powershell
.\scripts\install_windows_startup.ps1
```

To install and start both tasks immediately:

```powershell
.\scripts\install_windows_startup.ps1 -StartNow
```

The tasks start on user logon and use the project root as their working directory.

## Uninstall

```powershell
.\scripts\uninstall_windows_startup.ps1
```

This removes only:

- `GarnerQuantRuntime`
- `GarnerQuantDashboard`

It does not delete project files or logs.

## Check If Tasks Are Running

```powershell
Get-ScheduledTask -TaskName GarnerQuantRuntime,GarnerQuantDashboard
Get-ScheduledTaskInfo -TaskName GarnerQuantRuntime
Get-ScheduledTaskInfo -TaskName GarnerQuantDashboard
```

You can also open Task Scheduler and look for the two tasks by name.

## View Logs

Runtime log:

```powershell
Get-Content .\logs\runtime.log -Tail 100 -Wait
```

Dashboard log:

```powershell
Get-Content .\logs\dashboard.log -Tail 100 -Wait
```

Runtime state files:

- `data/live_runtime_status.json`
- `data/runtime_operations_log.json`
- `data/live_monitor_snapshot.json`

## Stop Tasks Manually

```powershell
Stop-ScheduledTask -TaskName GarnerQuantRuntime
Stop-ScheduledTask -TaskName GarnerQuantDashboard
```

Start them again:

```powershell
Start-ScheduledTask -TaskName GarnerQuantRuntime
Start-ScheduledTask -TaskName GarnerQuantDashboard
```

## Keep The PC Awake

For local server mode, the PC must stay awake and connected to WiFi or Ethernet.

Recommended Windows settings:

- Settings > System > Power
- Set sleep to `Never` while plugged in
- Disable hibernation if it interrupts long-running tasks
- Keep the lid open or configure laptop lid close behavior if using a laptop

Optional PowerShell check:

```powershell
powercfg /query
```

## Access From iPhone On Home WiFi

Find your Windows PC IP address:

```powershell
ipconfig
```

Look for the IPv4 address on your WiFi or Ethernet adapter, then open this on your iPhone while connected to the same home WiFi:

```text
http://YOUR_PC_IP:8501
```

Example:

```text
http://192.168.1.25:8501
```

If the page does not load:

- Confirm the dashboard task is running
- Confirm `logs/dashboard.log` does not show Streamlit startup errors
- Allow Python or port `8501` through Windows Firewall for private networks
- Make sure the iPhone is on the same WiFi network as the PC
