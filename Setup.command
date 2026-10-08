#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin"
trap 'print "Setup failed. Read the error above, then consult START HERE.md."; read "reply?Press Return to close. "' ZERR
if [[ "$(uname -s)" != Darwin ]]; then print "This package is for macOS."; exit 1; fi
if [[ ! -x /usr/bin/networkQuality ]]; then print "This Mac lacks Apple networkQuality. A newer macOS is required for speed tests."; exit 1; fi
if ! command -v python3 >/dev/null || ! python3 -c 'import sys; sys.exit(sys.version_info < (3,10))'; then
  if command -v brew >/dev/null; then
    print "Installing Python with your existing Homebrew..."
    brew install python
  else
    print "Install Python 3.10 or newer from https://www.python.org/downloads/macos/ or install Homebrew from https://brew.sh, then rerun Setup.command."
    read "reply?Press Return to close. "
    exit 1
  fi
fi
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python doctor.py
print "Setup complete. Double-click Start Router Lab.command."
print "MTR is optional and may need a separate installation/permission step; see START HERE.md."
read "reply?Press Return to close. "
