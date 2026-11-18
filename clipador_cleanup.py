"""Remove generated video files only after all requested networks confirmed them."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib,json,re

_NETWORKS = {'tiktok','instagram','youtube'}
_NAME = re.compile(r'(.+)_(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})\Z')

def _digest(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file,'sha256').digest()

def limpar_publicado(video, clipes_root, plataformas, log=print, legacy_root=None):
    video=Path(video)
    root=Path(clipes_root).resolve()
    networks=list(dict.fromkeys(plataformas))
    if not networks or any(network not in _NETWORKS for network in networks):
        return 0
    if not video.resolve().is_relative_to(root):
        raise ValueError('Arquivo publicado fora da pasta de clipes; limpeza recusada.')
    if any(not video.with_name(video.stem+'.'+network+'.ok').is_file() for network in networks):
        log('Limpeza adiada: ainda falta confirmação de uma rede para '+video.name)
        return 0
    if legacy_root is None:
        from clipador.caminhos import BASE_DIR
        import os
        original=os.environ.get('CLIPADOR_ORIGINAL_INSTALL')
        install=Path(original) if original else BASE_DIR
        if not (install/'Clipador.exe').is_file() or not (install/'_internal').is_dir():
            install=BASE_DIR
        legacy_root=install/'clipes'
    legacy=Path(legacy_root).resolve()
    pending=any(path.resolve()!=video.resolve()
                for folder in (root/'PRONTOS PARA POSTAR',root/'falhou_postar')
                for path in folder.rglob(video.name))
    candidates=[video]
    match=_NAME.fullmatch(video.stem)
    if match and not pending:
        basename=match[1]+'_'+match[3]
        for base in dict.fromkeys((root,legacy)):
            for suffix in ('.bruto.mp4','.cortado.mp4','.vertical.mp4'):
                candidates.append(base/match[2]/(basename+suffix))
        # Retired install-folder queue copies are removed only when byte-identical.
        if legacy!=root and video.is_file():
            signature=None
            for copy in (legacy/'PRONTOS PARA POSTAR').rglob(video.name):
                if not copy.is_file() or not copy.resolve().is_relative_to(legacy):continue
                if signature is None:signature=_digest(video)
                if _digest(copy)==signature:candidates.append(copy)
    proof=video.with_suffix('.publicacao.json')
    record={'video':video.name,'redes_confirmadas':networks,
            'confirmado_em':datetime.now(timezone.utc).isoformat(),
            'fontes_preservadas_por_pendencia':pending,'arquivos_removidos':[],'falhas_limpeza':[]}
    # Keep durable confirmation independently of the media files.
    proof.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    for path in dict.fromkeys(candidates):
        resolved=path.resolve()
        if not any(resolved.is_relative_to(base) for base in (root,legacy)):
            continue
        if not path.is_file():continue
        try:
            path.unlink()
            record['arquivos_removidos'].append(str(path))
        except OSError as error:
            record['falhas_limpeza'].append({'arquivo':str(path),'erro':str(error)})
            log('Não foi possível remover '+str(path)+': '+str(error))
    proof.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    log('Limpeza após publicação confirmada: '+str(len(record['arquivos_removidos']))+' arquivo(s) de vídeo removido(s) para '+video.name)
    return len(record['arquivos_removidos'])
