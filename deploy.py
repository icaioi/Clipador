"""Install the generated executables only after Clipador has been stopped."""
from package import ROOT
from pathlib import Path
import datetime,shutil,os,subprocess

names=('Clipador.exe','ClipadorWorker.exe')
for name in names:
    if not (ROOT/(name+'.youtube-ready')).is_file():
        raise RuntimeError('Run integrate.py before deployment: missing '+name)
backup=ROOT/('backup-antes-atualizacao-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir()
for name in names:
    shutil.copy2(ROOT/name,backup/name)
config=Path.home()/'Documents'/'Clipador'/'canais.toml'
if config.is_file():
    shutil.copy2(config,backup/'canais.toml')
for name in names:
    os.replace(ROOT/(name+'.youtube-ready'),ROOT/name)
print('Installed; backup:',backup)
result=subprocess.run([str(ROOT/'Clipador.exe'),'--teste'],cwd=ROOT,capture_output=True,text=True,errors='replace',timeout=30)
print('Installed GUI smoke exit:',result.returncode)
if result.stderr:
    print(result.stderr[-1000:])
if result.returncode:
    raise RuntimeError('Installed GUI smoke failed')
