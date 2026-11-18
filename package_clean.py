"""Create a portable bundle from program resources, never from user data."""
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime
import json,marshal,os,re,subprocess,sys,tomllib,zipfile
from package import Package,ROOT
from integrate import all_transforms

from distribution import CLEAN_CONFIG, allowed, private_needles, scan as scan_bytes, scan_file, resources as clean_resources

needles=private_needles(ROOT)
def scan(data,label):
    scan_bytes(data,label,needles)

resources=list(clean_resources(ROOT))

desktop=Path.home()/'Desktop'
output=(desktop if desktop.is_dir() else ROOT.parent)/('Clipador-para-enviar-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip')
transforms=all_transforms()
with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for name in ('Clipador.exe','ClipadorWorker.exe'):
        package=Package(name)
        for module in package.toc:
            if module.startswith('clipador'):
                code=package.module(module)
                if module in transforms:code=transforms[module](code)
                scan(marshal.dumps(code),name+':'+module)
        data=package.build(transforms)
        scan(data,name)
        archive.writestr('Clipador/'+name,data)
    archive.writestr('Clipador/_internal/canais.toml',CLEAN_CONFIG)
    for source,relative in sorted(resources):
        scan_file(source,str(relative),needles)
        archive.write(source,'Clipador/'+relative.as_posix())
print('Created portable ZIP:',output,flush=True)
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None,'Archive integrity failure'
    assert all(allowed(Path(name).relative_to('Clipador')) for name in archive.namelist())
    config=tomllib.loads(archive.read('Clipador/_internal/canais.toml').decode('utf-8'))
    assert config['canais']==[] and config['ia']['chave']=='' and config['marca']['texto']==''
    with TemporaryDirectory(prefix='clipador-share-check-') as temporary:
        home=Path(temporary)/'new-user';home.mkdir()
        program=Path(temporary)/'program';archive.extractall(program)
        env={key:value for key,value in os.environ.items() if not re.search(r'API.?KEY|TOKEN|SECRET|PASSWORD|COOKIE|SESSION|GEMINI',key,re.I)}
        for key,value in {'USERPROFILE':home,'HOME':home,'APPDATA':home/'AppData/Roaming','LOCALAPPDATA':home/'AppData/Local','TEMP':home/'Temp','TMP':home/'Temp'}.items():
            Path(value).mkdir(parents=True,exist_ok=True);env[key]=str(value)
        exe=program/'Clipador'/'Clipador.exe'
        result=subprocess.run([str(exe),'--teste'],cwd=exe.parent,env=env,capture_output=True,timeout=40)
        assert result.returncode==0,'Clean-profile startup failed'
        data_root=home/'Documents'/'Clipador'
        first=tomllib.loads((data_root/'canais.toml').read_text(encoding='utf-8'))
        assert first['canais']==[] and first['ia']['chave']==''
        assert not any(path.name.casefold() in {'cookies','login data'} for path in data_root.rglob('*'))
        print(json.dumps({'archive_integrity':True,'clean_profile_gui_exit':result.returncode,'configured_channels':0,'user_api_key_included':False,'saved_account_sessions':False}),flush=True)
print(json.dumps({'zip':str(output),'bytes':output.stat().st_size,'included_files':len(resources)+3}),flush=True)
