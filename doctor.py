"""Read-only prerequisite check; does not send network probes or alter permissions."""
import importlib.util
import platform
import shutil
import subprocess
import sys

search='/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin'
required=['ping','curl','dig','networkQuality','networksetup','route','ifconfig','ipconfig']
missing=[]
if platform.system()!='Darwin': missing.append('macOS')
if sys.version_info<(3,10): missing.append('Python 3.10+')
if importlib.util.find_spec('reportlab') is None: missing.append('reportlab (run Setup.command)')
for name in required:
    if not shutil.which(name,path=search): missing.append(name)
speed=shutil.which('networkQuality',path=search)
if speed:
    help_run=subprocess.run([speed,'-h'],capture_output=True,text=True,timeout=5)
    help_text=help_run.stdout+help_run.stderr
    if any(flag not in help_text for flag in ['-c','-s','-I','-M']):
        missing.append('networkQuality with -c/-s/-I/-M support (update macOS)')
mtr=shutil.which('mtr',path=search)
print('MTR: '+(mtr+' (permissions checked when run)' if mtr else 'not installed; optional, see START HERE.md'))
if missing:
    print('Missing requirements: '+', '.join(missing));sys.exit(1)
print('Core requirements OK. Local web app, PDF reports, ping, DNS, HTTPS and speed tests are available.')
