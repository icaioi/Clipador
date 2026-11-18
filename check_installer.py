"""Exercise the real frozen install button and bundled Node CLI without downloads."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json,subprocess
from package import Package,ROOT,walk
from installer_transform import transform

HERE=Path(__file__).parent

def run():
    package=Package()
    original=package.module('clipador.gui.__main__')
    patched=transform(original)
    target='TelaInicio._instalar_componentes.<locals>.rodar_instalacao'
    before=next(c for c in walk(original) if c.co_qualname==target)
    after=next(c for c in walk(patched) if c.co_qualname==target)
    assert before.co_argcount==after.co_argcount==0
    assert before.co_freevars==after.co_freevars==('btn_fechar','label_status','progress','seguro','self','ui')
    with TemporaryDirectory(prefix='clipador-installer-') as folder:
        result=Path(folder)/'result.json'
        entry='''
import sys,json,time,traceback,subprocess
from pathlib import Path
sys.path.insert(0,LOCAL_SOURCE)
output=Path(RESULT_PATH)
app=None
try:
    from clipador_componentes import comando_instalacao
    from clipador.platform_utils import creation_flags
    command=comando_instalacao()
    assert Path(command[0]).name.lower()=='node.exe',command[0]
    assert '-m' not in command
    dry=subprocess.run(command[:-1]+['--dry-run',command[-1]],capture_output=True,text=True,encoding='utf-8',errors='replace',creationflags=creation_flags(),timeout=60)
    assert dry.returncode==0,dry.stderr or dry.stdout
    assert 'chromium' in dry.stdout.lower(),dry.stdout
    from clipador.gui import __main__ as gui
    app=gui.ClipadorApp(teste=True)
    app.janela=gui.ctk.CTk()
    app.janela.title('Clipador - teste isolado do instalador')
    app.frame_conteudo=gui.ctk.CTkFrame(app.janela)
    app.frame_conteudo.pack(fill='both',expand=True)
    screen=gui.TelaInicio(app)
    screen.pack(fill='both',expand=True)
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    button=next(w for w in descendants(screen) if isinstance(w,gui.ctk.CTkButton) and getattr(getattr(w,'_command',None),'__name__','')=='_instalar_componentes')
    button.invoke()
    dialog=next(w for w in app.janela.winfo_children() if isinstance(w,gui.ctk.CTkToplevel))
    children=list(descendants(dialog))
    progress=next(w for w in children if isinstance(w,gui.ctk.CTkProgressBar))
    close=next(w for w in children if isinstance(w,gui.ctk.CTkButton))
    labels=[w for w in children if isinstance(w,gui.ctk.CTkLabel)]
    deadline=time.monotonic()+90
    app._drenar_fila_ui()
    while close.cget('state')!='normal' and time.monotonic()<deadline:
        app.janela.update()
        time.sleep(0.02)
    app.janela.update()
    statuses=[w.cget('text') for w in labels]
    assert close.cget('state')=='normal','Installer did not finish'
    assert progress.get()==1,statuses
    assert gui.t('chromium_ok') in statuses,statuses
    output.write_text(json.dumps({'frozen':bool(sys.frozen),'button_invoked':True,'progress':progress.get(),'status':gui.t('chromium_ok'),'close_enabled':True,'node_cli_dry_run':dry.returncode,'downloads_performed':False}),encoding='utf-8')
except BaseException:
    output.write_text(json.dumps({'error':traceback.format_exc()}),encoding='utf-8')
finally:
    if app is not None and app.janela is not None:
        app.janela.destroy()
'''.replace('LOCAL_SOURCE',repr(str(HERE))).replace('RESULT_PATH',repr(str(result)))
        probe=ROOT/'Clipador-installer-probe.exe'
        assert not probe.exists(),probe
        try:
            probe.write_bytes(package.build({'clipador.gui.__main__':transform},entry=entry))
            process=subprocess.Popen([str(probe)],cwd=ROOT)
            try:
                code=process.wait(timeout=170)
            except subprocess.TimeoutExpired:
                process.kill();process.wait()
                raise
            assert result.is_file(),('Probe did not report',code)
            report=json.loads(result.read_text(encoding='utf-8'))
            assert 'error' not in report,report.get('error')
            assert code==0,code
            print(json.dumps(report,ensure_ascii=False))
        finally:
            probe.unlink(missing_ok=True)

if __name__=='__main__':run()
