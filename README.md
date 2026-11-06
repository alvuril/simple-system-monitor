# System Monitor

A clean, minimal system monitor for Windows. Everything is optional: turn features on and off in the built-in settings page.

## Download

Grab `SystemMonitor.exe` from the [Releases](../../releases) page and double-click it. No installation or Python needed.

Windows may show a SmartScreen warning for unsigned apps: click **More info → Run anyway**.

## Features

**Metrics** (each can be shown or hidden)
- CPU usage with live graph, per-core bars, and clock speed
- Memory and swap / page file
- Disk usage for any drive, plus disk read / write speed
- Network download / upload speed (MB/s or Mbps) with optional graph
- NVIDIA GPU load, VRAM and temperature (needs NVIDIA drivers)
- Battery level, charging state and time remaining
- Uptime
- Top processes by CPU or memory (type in how many to show)

**Appearance**
- Themes: Dark, Black, Nord, Light
- Six accent colors
- Window opacity, compact layout, always on top, borderless (drag to move)

**Behavior**
- Update speed from 0.5 to 5 seconds, adjustable graph history
- Alerts when CPU or memory pass a threshold, with optional sound
- CSV logging to `%APPDATA%\SystemMonitor\log.csv`
- Start with Windows
- Remembers window position and all settings

Open settings with the **SETTINGS** button. Click a value to change it; right-click to step backwards.

## Build from source

```
pip install -r requirements.txt
python sysmon.py
```

To build the `.exe` yourself, run `build.bat`. Or let GitHub do it: push a tag like `v1.0.0` and the workflow in `.github/workflows/build.yml` builds the app and attaches it to a Release.

## License

MIT
