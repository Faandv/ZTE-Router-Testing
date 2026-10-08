#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin"
if [[ ! -x .venv/bin/python ]]; then
  print "First double-click Setup.command. If you moved this folder after setup, rerun setup."
  read "reply?Press Return to close. "
  exit 1
fi
if ! .venv/bin/python doctor.py; then
  print "Run Setup.command to resolve the missing requirements."
  read "reply?Press Return to close. "
  exit 1
fi
print "Keep this Terminal window open while testing. Press Control-C to stop the service."
.venv/bin/python launch.py || { print "Router Lab stopped with an error. See above."; read "reply?Press Return to close. "; }
