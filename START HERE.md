# Router Lab — Mac edition

This is a working copy of the router test app, not a specification to rebuild. It runs on your Mac and opens in your browser. No Codex subscription is needed to run it.

## First use

1. Extract the ZIP and move **Router Lab Mac** to a permanent folder, such as Documents. Keep all files together.
2. Double-click **Setup.command**. It checks Python and installs the PDF dependency into a private `.venv` inside this folder. Internet access is needed for setup. If Homebrew is present but a suitable Python is missing, setup installs Python through Homebrew. Otherwise it directs you to install Python 3.10+ first.
3. Double-click **Start Router Lab.command**. Keep its Terminal window open. The app opens at http://127.0.0.1:8765.
4. Select your Ethernet or Wi-Fi interface and verify the router LAN address. For ZTE status capture, enter your router admin password for each recording, or turn capture off for connectivity-only tests. No saved credentials are included.
5. Start recording before changing the WAN cable. Click each cable marker once and check for the green SAVED confirmation. Allow 60 seconds of stable connectivity between changes. Leave speed tests off during initial failover timing tests.
6. Stop recording in the app, then export PDF, JSON or CSV. Control-C in Terminal stops the service.

Use **Record WAN failover (DHCP / PPPoE)** for free-form recording. Configure PPPoE on the router, not in this app. Record the protocol/firmware in the session notes; do not put passwords in notes. Router API capture has been tested against a ZTE G5TS Pro / MC8500 firmware variant; different firmware can require adapter changes. Connectivity monitoring works independently.

## Mac prerequisites

Apple Silicon and Intel tool locations are supported. Python 3.10+ and macOS with `networkQuality -c -s -I -M` are required. Setup checks those flags without running a speed test. Older macOS versions may lack them. Python: https://www.python.org/downloads/macos/ . Homebrew installation: https://docs.brew.sh/Installation . Follow official installers; this package does not install Homebrew or change macOS security settings.

If a downloaded launcher is blocked, review the files and use your organisation's approved method for opening trusted local scripts. A Terminal alternative is `zsh Setup.command` and then `zsh "Start Router Lab.command"` from the extracted folder. Do not disable Gatekeeper globally. If macOS asks for Local Network access, allow it if you want to test your router.

## MTR is an optional extra

Install with `brew install mtr` if Homebrew is installed. Homebrew documents that MTR requires root privileges: https://formulae.brew.sh/formula/mtr . Merely installing it may not make the app's **Run MTR** button work. The app runs as your ordinary user and does not silently elevate privileges or change helper permissions.

If MTR reports a permission error, ask your IT administrator to configure the MTR packet helper for your Mac, or run `sudo mtr -4 --report --report-cycles 10 --no-dns 1.1.1.1` separately in Terminal and save that output alongside the app report. The separate command uses the default route and is not automatically attached to an app session. Never launch the whole web app with sudo. Other tests work without MTR.

## Data and troubleshooting

- Everything you record is saved in `data/` next to the app. This ZIP contains no recordings, router passwords, reports or saved credentials.
- To share the app onward, use the original clean ZIP. Do not zip your used folder: it will contain your test data.
- Speed tests can use several gigabytes. Router/public pings, DNS and HTTPS contact the endpoints shown in the app; the optional public-IP button contacts ipwho.is.
- The app measures sampled responses with short timeouts. Load-related probe timeouts do not alone prove a router fault. Tests cover IPv4, not existing-call/VPN continuity.
- Keep the Mac awake and connected to the router. Close unrelated downloads and avoid a VPN during comparisons.
- If you move the folder after setup, rerun Setup.command to recreate the environment at its new location.
- If port 8765 is occupied, close the other app or start with `ROUTER_LAB_PORT=8766 zsh "Start Router Lab.command"`.
- `python3 doctor.py` checks prerequisites. For an issue, give Codex this whole folder and **CODEX HANDOVER.md**; it should adapt this app, not rebuild it from scratch.

## Verification and limitations

The source regression suite and extracted-package smoke check were run on the packaging Mac. Installation on your specific Mac still needs the setup check. Python dependencies are downloaded at setup; this is not an offline, signed or notarised app bundle. No router settings are changed by the recorder.
