# Set up this existing Router Lab app

User request to paste into Codex:

> Help me set up and run the existing Router Lab app in this folder on my Mac. Read START HERE.md and this handover. Inspect the existing code rather than rebuilding it. Run prerequisite checks, install the documented local Python environment if needed, and launch the app. Keep the service loopback-only and run it as my ordinary user. If MTR lacks permission, explain the specific limitation and ask before granting privileged access. Do not change my router settings. Ask for the router address/password only if I want router status capture. Verify the app opens and has empty session history on a fresh install.

## Structure

- server.py: local HTTP service, SQLite, parallel network probes, diagnostics and exports.
- router_client.py: verified read-only ZTE /ubus adapter; firmware dependent.
- recording_report.py: derived marker attribution; original measurements preserved.
- report.py: ReportLab PDF export.
- static/: browser UI with persistent cable-marker acknowledgements.
- Setup.command / Start Router Lab.command / doctor.py: portable Mac setup and launcher.
- requirements.txt: runtime dependencies; requirements-dev.txt: test dependencies.
- test_lab.py: isolated simulated regressions. Run `.venv/bin/python -m pip install -r requirements-dev.txt` then `.venv/bin/python -m unittest discover -p "test_*.py"`.

Read-only router access is optional. Never infer a WAN switch solely from a manual marker or internet recovery. PPPoE credentials belong in the router admin, not app notes. Near-marker attribution is a declared timing association, not proof of causation. Speed-loaded samples stay out of failover detection but remain in overall ping statistics. Preserve these semantics when adapting the code.

Tool discovery supports Homebrew prefixes for both Mac architectures. MTR privilege setup is machine-dependent; do not solve it by running the web server as root. Stop and explain if this Mac lacks compatible networkQuality flags. Keep user data and credentials out of distribution packages; package files by explicit allowlist.
