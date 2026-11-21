from pathlib import Path
import runpy,types,sys
from package import Package,ROOT,walk
from build import capture_transforms,replace_functions,functions,deploy_helpers
from pipeline_transforms import caminhos, app_counter, cortador_counter
from poster_runtime_transform import transform as poster_runtime
from gui_resume_transform import transform as gui_resume
from background_transform import transform as background
from cleanup_transform import transform as cleanup
from tutorial_transform import transform as tutorial
from installer_transform import transform as installer
from monitor_transform import transform as monitor
HERE=Path(__file__).parent
RUNTIME_HELPERS=('clipador_youtube.py','youtube_chat.py','clipador_contas.py',
                 'clipador_cleanup.py','clipador_tutorial.py','clipador_componentes.py',
                 'clipador_monitor.py','clipador_updater.py','clipador_launcher.py','clipador_pending.py')

def source_codes(name):
    code=compile((HERE/name).read_text(encoding='utf-8'),name,'exec')
    return {c.co_qualname:c for c in walk(code)}

def constants_transform(mapping):
    def run(c):
        return c.replace(co_consts=tuple(run(v) if isinstance(v,types.CodeType) else mapping.get(v,v) if isinstance(v,str) else v for v in c.co_consts))
    return run

def all_transforms():
    transforms=capture_transforms()
    app_code=functions(HERE/'app_replacements.py')
    app_main=replace_functions({'main':app_code['main']})
    capture_app=transforms['clipador.app']
    transforms['clipador.app']=lambda code:background(app_main(capture_app(code)))
    codes=source_codes('youtube_ui_methods.py')
    declarations=runpy.run_path(str(HERE/'youtube_ui_methods.py'))
    gui_transform=replace_functions({old:codes[new] for old,new in declarations['REPLACEMENTS'].items()})
    process_codes=source_codes('process_replacements.py')
    shutdown=replace_functions({'ClipadorApp._parar_tudo.<locals>.encerrar':process_codes['shutdown_factory.<locals>.encerrar']})
    transforms['clipador.gui.__main__']=lambda code:tutorial(installer(background(shutdown(gui_resume(gui_transform(code))))))
    for module,changes in declarations['CONSTANT_TRANSFORMS'].items():
        transforms[module]=constants_transform(changes)
    chat=functions(HERE/'chat_replacements.py')
    transforms['clipador.chat']=replace_functions({'iniciar_chats':chat['iniciar_chats']})
    main=functions(HERE/'main_replacements.py')
    main_transform=replace_functions({'teste_chat':main['teste_chat']})
    transforms['clipador.__main__']=lambda code:monitor(app_counter(main_transform(code)))
    transforms['clipador.caminhos']=caminhos
    transforms['clipador.cortador']=cortador_counter
    postador=functions(HERE/'postador_replacements.py')
    publication=functions(HERE/'publication_replacements.py')
    postador_main=replace_functions({'main':postador['main'],'_esperar_publicacao':publication['_esperar_publicacao']})
    transforms['clipador.postador']=lambda code:cleanup(poster_runtime(postador_main(code)))
    processes=functions(HERE/'process_replacements.py')
    transforms['clipador.platform_utils']=replace_functions({'creation_flags':processes['creation_flags'],'kill_proc':processes['kill_proc']})
    return transforms

if __name__=='__main__':
    deploy_helpers(RUNTIME_HELPERS)
    transforms=all_transforms()
    for name in ('Clipador.exe','ClipadorWorker.exe'):
        (ROOT/(name+'.youtube-ready')).write_bytes(Package(name).build(transforms))
        print('Prepared',name)
