"""Exercise the real frozen poster loop without browser, login or social requests."""
from pathlib import Path
import json,os,subprocess,tempfile,uuid
from package import Package,ROOT
from integrate import all_transforms
from distribution import CLEAN_CONFIG

ENTRY=r'''
from pathlib import Path
import json,os,sys
from types import SimpleNamespace
source,report=map(Path,sys.argv[1:]);sys.path.insert(0,str(source))
from playwright import sync_api
from clipador import postador
from clipador.caminhos import pasta_dados
import clipador_cleanup
actual_cleanup=clipador_cleanup.limpar_publicado
clipador_cleanup.limpar_publicado=lambda video,clipes,platforms,log=print: actual_cleanup(
    video,clipes,platforms,log,legacy_root=root/'isolated-legacy')
root=pasta_dados()/'clipes';ready=root/'PRONTOS PARA POSTAR';failed=root/'falhou_postar';posted=root/'postados'
class Driver:
    def __enter__(self):return self
    def __exit__(self,*args):return False
sync_api.sync_playwright=Driver
postador._abrir=lambda driver:SimpleNamespace(browser=SimpleNamespace(is_connected=lambda:True),pages=[object()],close=lambda:None)
postador._alarme=lambda text:None
postador.random.uniform=lambda *args:0
postador.NOTA_MINIMA=6
logs=[];calls=[];completed=0;limit=1
def log(text):
    global completed
    logs.append(text)
    if 'próximo post em ' in text:
        completed+=1
        if completed>=limit:raise KeyboardInterrupt()
postador._registrar=log

def clip(folder,index,proofs):
    folder.mkdir(parents=True,exist_ok=True)
    video=folder/f'canal_2026-11-20_10-00-{index:02d}.mp4'
    video.write_bytes(b'fixture-never-uploaded')
    video.with_suffix('.txt').write_text('fixture caption',encoding='utf-8')
    for network in proofs:video.with_suffix('.'+network+'.ok').touch()
    os.utime(video,(1000-index,1000-index))
    return video

def tiktok(ctx,video,caption,auto):
    calls.append(('tiktok',video.name))
    assert video.with_suffix('.instagram.ok').exists(),'Instagram confirmation was lost during recovery'
    return True

def instagram(ctx,video,caption,auto):
    calls.append(('instagram',video.name))
    raise AssertionError('Confirmed Instagram publication was duplicated')
postador.postar_tiktok=tiktok;postador.postar_instagram=instagram
video=clip(failed,1,['instagram'])
metadata=root/'2026-11-20'/'canal_10-00-01.json';metadata.parent.mkdir(parents=True);metadata.write_text(json.dumps({'nota':8}),encoding='utf-8')
postador.rodar(True,['tiktok','instagram'],(0,0),perfil='principal',redes_perfil=['tiktok','instagram'])
assert calls==[('tiktok',video.name)],calls
assert not video.exists()
assert (posted/video.with_suffix('.instagram.ok').name).exists()
assert (posted/video.with_suffix('.tiktok.ok').name).exists()
assert not list(ready.rglob('*.mp4'))
first={'recovered_partial':True,'only_tiktok_called':True,'both_confirmations_preserved':True}

# Three TikTok failures must not drain later TikTok-only work, and must not
# prevent later Instagram work whose TikTok publication is already confirmed.
import shutil
shutil.rmtree(root);root.mkdir();calls.clear();logs.clear();completed=0;limit=4
for index in (1,2,3,4):clip(ready/'nota 08',index,['instagram'])
last=clip(ready/'nota 08',5,['tiktok'])
def fail_tiktok(ctx,video,caption,auto):calls.append(('tiktok',video.name));return False
def pending_instagram(ctx,video,caption,auto):
    calls.append(('instagram',video.name));assert video.name==last.name;return True
postador.postar_tiktok=fail_tiktok;postador.postar_instagram=pending_instagram
postador.rodar(True,['tiktok','instagram'],(0,0),perfil='principal',redes_perfil=['tiktok','instagram'])
assert len([c for c in calls if c[0]=='tiktok'])==3,calls
assert [c for c in calls if c[0]=='instagram']==[('instagram',last.name)],calls
waiting=ready/'nota 08'/'canal_2026-11-20_10-00-04.mp4'
assert waiting.exists(),'Disabled-only pending media was consumed'
assert waiting.with_suffix('.instagram.ok').exists()
assert (posted/last.with_suffix('.tiktok.ok').name).exists()
assert (posted/last.with_suffix('.instagram.ok').name).exists()
report.write_text(json.dumps({'ok':True,'recovery':first,'disabled_only_kept_in_queue':True,'later_active_work_not_starved':True}),encoding='utf-8')
'''

def main():
    with tempfile.TemporaryDirectory(prefix='clipador-poster-check-') as temporary:
        folder=Path(temporary);home=folder/'user';data=home/'Documents'/'Clipador';data.mkdir(parents=True)
        (data/'canais.toml').write_text(CLEAN_CONFIG,encoding='utf-8')
        env=os.environ.copy()
        for key,path in {'USERPROFILE':home,'HOME':home,'APPDATA':folder/'roaming','LOCALAPPDATA':folder/'local','TEMP':folder/'temp','TMP':folder/'temp'}.items():
            path.mkdir(exist_ok=True);env[key]=str(path)
        report=folder/'result.json';probe=ROOT/('ClipadorPendingCheck-'+uuid.uuid4().hex+'.exe')
        try:
            entry='try:\n'+''.join('    '+line+'\n' for line in ENTRY.splitlines())+"""
except BaseException:
    from pathlib import Path
    import json,sys,traceback
    Path(sys.argv[2]).write_text(json.dumps({'ok':False,'error':traceback.format_exc()}),encoding='utf-8')
    raise SystemExit(1)
"""
            probe.write_bytes(Package().build(all_transforms(),entry=entry))
            result=subprocess.run([str(probe),str(Path(__file__).resolve().parent),str(report)],cwd=ROOT,env=env,capture_output=True,timeout=25)
            assert result.returncode==0,(report.read_text(encoding='utf-8') if report.exists() else 'Frozen poster check exited '+str(result.returncode))
            assert report.exists(),'Frozen poster check did not produce evidence'
            evidence=json.loads(report.read_text(encoding='utf-8'));assert evidence['ok'];print(json.dumps(evidence))
        finally:probe.unlink(missing_ok=True)
if __name__=='__main__':main()
