# ZTE Router Testing — Router Lab

A local browser app for testing wired-WAN to mobile failover on a Mac. Record what happens when you unplug and reconnect the WAN cable, inspect router status, and export the evidence.

## Quick start

1. Download this repository using **Code → Download ZIP**, or clone it.
2. Extract it into a permanent folder on your Mac.
3. Double-click **Setup.command** once. Setup creates a local Python environment and installs dependencies. Internet access is required.
4. Double-click **Start Router Lab.command**. Keep the Terminal window open while testing.
5. Open **http://127.0.0.1:8765** if the browser does not open automatically.

See [START HERE.md](START%20HERE.md) for prerequisites, permissions, troubleshooting and MTR setup. Codex can help install the existing app using [CODEX HANDOVER.md](CODEX%20HANDOVER.md); it is not needed to run the app.

## Features

- Ethernet and Wi-Fi interface selection.
- Continuous router/public ping, DNS and HTTPS checks, with live graphs and a timestamped timeline.
- Manual WAN plugged/unplugged markers with persistent confirmation and duplicate-click protection.
- Connectivity recovery timing and guided failover workflow.
- Read-only ZTE status capture: operating mode, active-interface evidence, WAN addresses, mobile radio readings and API responsiveness.
- Apple networkQuality speed tests, MTR and standalone ping diagnostics.
- Session history, comparisons, PDF reports and CSV/JSON exports.
- DHCP or PPPoE upstream testing. Configure the WAN protocol and credentials on the router itself.

## A first failover test

1. Connect your Mac to a router LAN port. Keep mobile service ready and confirm the router's desired failover configuration.
2. Select **Record WAN failover (DHCP / PPPoE)**, the correct Ethernet interface and the starting WAN.
3. Enable router capture and enter your own router admin password, or leave capture off for connectivity-only testing.
4. Start recording and allow 60 seconds of stable wired connectivity.
5. Unplug only the router WAN cable; immediately click **WAN unplugged** once.
6. Wait for recovery, then observe for 60 seconds. Reconnect WAN and click **WAN plugged in** once.
7. Observe recovery and another 60 seconds of stability, then stop and export the results.

Keep speed tests off during the first failover run. Speed-loaded samples are excluded from outage detection but remain in overall packet-loss statistics.

## Supported environment and interpretation

- macOS with compatible Apple `networkQuality` flags (`-c`, `-s`, `-I`, `-M`), Python 3.10+, and ReportLab. Setup checks compatibility. Apple Silicon and Intel Homebrew locations are supported.
- MTR is optional and may need administrator configuration. Do not run the web app as root.
- The read-only router adapter was tested with ZTE G5TS Pro / MC8500 firmware BD_AFHZAMC8500V1.0.0B04. Other firmware and models may require adaptation.
- IPv4 measurements only. The app does not test uninterrupted calls, VPN sessions or IPv6 failover.
- Recovery requires three consecutive samples with HTTPS success and at least one public ping reply. DNS is reported separately.
- Timings are sampled observations relative to clicks, not exact hardware cable timestamps. A nearby interruption beginning up to five seconds before a marker is explicitly associated by timing, not proven causation.
- Where firmware omits the wired-interface name, corroborating Auto DHCP/interface/address fields can identify **Wired WAN - DHCP (inferred)**. Missing, conflicting or stale evidence remains unconfirmed. Diagnostic labels describe the router observation at test start.
- A successful internet probe alone does not prove which WAN carried traffic. Short probe timeouts under load do not establish a hardware defect.

## Data and privacy

The server listens on **127.0.0.1** only. Recordings and SQLite history live in `data/`; the repository contains no test history, credentials or demo footage. Passwords entered for a session are not saved by the form. Do not commit locally added credential files or share your used app folder without reviewing it.

Network tests contact their configured public endpoints. The optional public-IP lookup contacts ipwho.is. Exports can contain network addresses, router metadata and your notes; review them before sharing.

## Development and clean distribution

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -p 'test_*.py'
.venv/bin/python build_distribution.py
```

The builder creates `dist/Router-Lab-Mac.zip` from an explicit source allowlist. It never includes local recordings or credentials. `ROUTER_LAB_PORT` and `ROUTER_LAB_DATA` override the default port and storage directory.

Core implementation: `server.py` (HTTP service/probes), `router_client.py` (read-only adapter), `wan_labels.py` (timestamped path interpretation), `recording_report.py` (marker attribution), `report.py` (PDF) and `static/` (UI).
