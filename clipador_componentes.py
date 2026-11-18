"""Install with Playwright's bundled Node CLI, not Python flags on a frozen EXE."""
from pathlib import Path
import subprocess,traceback
from playwright._impl._driver import compute_driver_executable
from playwright.sync_api import sync_playwright
from clipador.platform_utils import creation_flags
from clipador.caminhos import pasta_dados

def comando_instalacao():
    node,cli=compute_driver_executable()
    return [str(node),str(cli),'install','chromium']

def instalar(log=print):
    arquivo=pasta_dados()/'instalacao-componentes.log'
    arquivo.parent.mkdir(parents=True,exist_ok=True)
    def registrar(texto):
        with arquivo.open('a',encoding='utf-8') as file:file.write(texto+'\n')
        log(texto)
    try:
        with sync_playwright() as driver:
            executable=Path(driver.chromium.executable_path)
        if not executable.is_file():
            registrar('Instalando Chromium pelo driver incluído no Clipador...')
            with subprocess.Popen(comando_instalacao(),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                    text=True,encoding='utf-8',errors='replace',creationflags=creation_flags()) as process:
                last=''
                for line in process.stdout:
                    if line.strip():
                        last=line.strip()
                        registrar(last)
                code=process.wait()
            if code:
                raise RuntimeError('Instalação falhou (código '+str(code)+'). '+last)
        else:
            registrar('Chromium já incluído. Verificando se abre corretamente...')
        with sync_playwright() as driver:
            browser=driver.chromium.launch(headless=True,channel='chromium')
            try:
                if not browser.is_connected():raise RuntimeError('Chromium abriu sem conexão com o driver.')
                registrar('Chromium verificado: '+browser.version)
            finally:browser.close()
        if not executable.is_file():
            raise RuntimeError('O instalador terminou, mas o executável do Chromium não foi encontrado.')
        return executable
    except Exception as error:
        registrar(traceback.format_exc())
        resumo=str(error).splitlines()[0] if str(error) else type(error).__name__
        raise RuntimeError(resumo+'\nConsulte '+str(arquivo)+' e tente instalar novamente.') from error
