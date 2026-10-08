"""Create a shareable ZIP using an explicit source allowlist."""
from pathlib import Path
import hashlib
import zipfile

ROOT=Path(__file__).resolve().parent
FILES=['README.md','START HERE.md','CODEX HANDOVER.md','Setup.command','Start Router Lab.command','doctor.py',
       'server.py','launch.py','router_client.py','recording_report.py','wan_labels.py','report.py',
       'test_lab.py','test_wan_labels.py','requirements.txt','requirements-dev.txt',
       'static/index.html','static/app.js','static/style.css','static/favicon.svg','build_distribution.py','.gitignore']

def main():
    dest=ROOT/'dist';dest.mkdir(exist_ok=True)
    archive=dest/'Router-Lab-Mac.zip'
    manifest=[]
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name in FILES:
            path=ROOT/name
            if path.is_symlink():raise ValueError('Distribution source must not be a symlink: '+name)
            data=path.read_bytes()
            item=zipfile.ZipInfo('Router Lab Mac/'+name)
            item.create_system=3
            item.external_attr=(0o100755 if name.endswith('.command') else 0o100644)<<16
            item.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(item,data)
            manifest.append(hashlib.sha256(data).hexdigest()+'  '+name)
        z.writestr('Router Lab Mac/SHA256SUMS.txt','\n'.join(manifest)+'\n')
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert len(z.namelist())==len(FILES)+1
    print(archive)

if __name__=='__main__':main()
