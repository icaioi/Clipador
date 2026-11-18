"""First-run progress uses configured profiles and actual execution evidence."""
from pathlib import Path
import json
from clipador_contas import estados

_NETWORKS=('tiktok','instagram','youtube')

def contas_concluidas(dados,perfis):
    dados=Path(dados)
    if not perfis:return False
    for perfil in perfis:
        if not perfil.redes:return False
        sessions=estados(perfil.pasta_navegador(dados/'perfil_navegador'))
        published=perfil.pasta_postados(dados/'clipes')
        for network in perfil.redes:
            if network not in _NETWORKS:return False
            # Onboarding records completing login, not present-day session validity.
            if sessions.get(network) is True:continue
            if next(published.glob('*.'+network+'.ok'),None) is not None:continue
            return False
    return True

def inicio_concluido(ativo,dados):
    dados=Path(dados)
    marker=dados/'primeiros_passos.json'
    try:
        completed=json.loads(marker.read_text(encoding='utf-8')).get('iniciou') is True
    except (OSError,ValueError,AttributeError):
        completed=False
    if ativo:
        if not completed:
            dados.mkdir(parents=True,exist_ok=True)
            temporary=marker.with_suffix('.tmp')
            temporary.write_text(json.dumps({'iniciou':True}),encoding='utf-8')
            temporary.replace(marker)
        return True
    if completed:return True
    published=dados/'clipes'/'postados'
    return any(next(published.rglob('*.'+network+'.ok'),None) is not None for network in _NETWORKS)

_BROWSER_EXECUTABLE=None

def componentes_instalados():
    global _BROWSER_EXECUTABLE
    if _BROWSER_EXECUTABLE is None:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as driver:
            _BROWSER_EXECUTABLE=Path(driver.chromium.executable_path)
    return _BROWSER_EXECUTABLE.is_file()
