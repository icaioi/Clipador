from package import Package,ROOT
from integrate import all_transforms
from pathlib import Path
import subprocess,tempfile
def html(message):
 return '<button data-e2e="post_video_button" style="width:180px;height:70px" onclick="document.querySelector(\'section\').innerText=\''+message+'\'">Publicar</button><section role="alert"></section>'
entry='''import json,pathlib,time,traceback,tempfile
result={}
try:
 from playwright.sync_api import sync_playwright
 from clipador import postador
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True)
  try:
   page=browser.new_page()
   page.set_content(ERROR_HTML)
   start=time.monotonic()
   try:postador._esperar_publicacao(page,'TikTok','Publicado com sucesso',True,'^Publicar$',timeout_min=.3)
   except RuntimeError as error:
    assert 'recusou a publicação' in str(error),str(error)
    assert time.monotonic()-start<15
   else:raise AssertionError('Site rejection incorrectly confirmed')
   page.set_content(SUCCESS_HTML)
   assert postador._esperar_publicacao(page,'Instagram','Publicado com sucesso',True,'^Publicar$',timeout_min=.3) is True
   result['ok']=True;result['tests']=['site error raises immediately instead of blocking other networks','visible success is required to confirm publication']
  finally:browser.close()
except BaseException:
 result['ok']=False;result['error']=traceback.format_exc()
(pathlib.Path(tempfile.gettempdir())/'publication_check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
'''
extra = """
 import tempfile
 with tempfile.TemporaryDirectory() as directory:
  postador.BASE_DIR=pathlib.Path(directory)
  postador.CLIPES_DIR=postador.BASE_DIR/'clipes'
  postador.LOG=postador.BASE_DIR/'test.log'
  postador._definir_perfil('principal')
  queue=postador._pasta_prontos()/'nota 07'
  queue.mkdir(parents=True)
  video=queue/'preservar.mp4'
  video.write_bytes(b'queue-fixture-not-uploaded')
  postador._alarme=lambda message:None
  try:
   postador.rodar(True,[],(0,0),perfil='principal')
  except RuntimeError:
   pass
  else:
   raise AssertionError('Empty network set did not stop')
  assert video.exists() and not list(postador._pasta_postados().glob('*.mp4'))
  result['tests'].append('no enabled networks preserves queue instead of marking videos posted')
"""
entry=entry.replace("  finally:browser.close()","  finally:browser.close()\n"+extra)
entry=entry.replace('ERROR_HTML',repr(html('Algo deu errado'))).replace('SUCCESS_HTML',repr(html('Publicado com sucesso')))
probe=ROOT/'ClipadorPublicationCheck.exe';probe.write_bytes(Package().build(all_transforms(),entry=entry))
r=subprocess.run([str(probe)],cwd=ROOT,capture_output=True,timeout=30)
print('Publication check exit',r.returncode)
p=Path(tempfile.gettempdir())/'publication_check.json';print(p.read_text(encoding='utf-8'))
assert __import__('json').loads(p.read_text(encoding='utf-8'))['ok']
probe.unlink()
