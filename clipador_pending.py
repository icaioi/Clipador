"""Return only unfinished failed publications to the caller's profile queue.

Confirmation files are evidence, not inferred state. Sidecars are staged using
no-clobber hard links before the media becomes visible; source evidence remains
in place until the media move commits. No user configuration is read here.
"""
from pathlib import Path
import json
import os
import re

_NETWORKS = {'tiktok', 'instagram', 'youtube'}
_NAME = re.compile(r'(.+)_(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})\Z')


def _safe(path, root):
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(root) or not path.resolve().is_relative_to(root):
        raise ValueError('Pasta ou arquivo fora da pasta de clipes: ' + str(path))
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('Link de pasta ou arquivo recusado: ' + str(part))
    return path


def _move_media(source, destination):
    # Windows rename never replaces a destination. POSIX rename does, so use
    # its no-copy, no-clobber link/unlink equivalent on that platform instead.
    if os.name == 'nt':
        os.rename(source, destination)
    else:
        os.link(source, destination)
        try:
            source.unlink()
        except OSError:
            destination.unlink()
            raise


def recuperar_pendentes(clipes_root, falhas, prontos, plataformas, log=print):
    """Recover canonical failed clips missing an enabled network; return count.

    ``falhas`` and ``prontos`` must be explicit, disjoint folders of the active
    profile under ``clipes_root``. Invalid networks are ignored. A collision or
    unsafe clip is logged and left untouched; missing metadata uses ``sem nota``.
    """
    networks = set(plataformas) & _NETWORKS
    if not networks:
        return 0
    root = Path(clipes_root).resolve()
    failed = _safe(falhas, root)
    ready = _safe(prontos, root)
    if failed.is_relative_to(ready) or ready.is_relative_to(failed):
        raise ValueError('Pastas de falhas e fila precisam ser separadas.')
    if not failed.exists():
        return 0
    recovered = 0
    try:
        videos = list(failed.iterdir())
    except OSError as error:
        log('Não foi possível ler a pasta de falhas: ' + str(error))
        return 0
    # Named profiles live below the principal failed folder. Never recurse.
    for video in videos:
        match = _NAME.fullmatch(video.stem)
        if video.suffix.lower() != '.mp4' or not match:
            continue  # Raw originals and unrelated files are not queue clips.
        staged = []
        committed = False
        try:
            _safe(video, root)
            if not video.is_file():
                continue
            sidecars = []
            for path in video.parent.iterdir():
                if (path.name in (video.stem + '.txt', video.stem + '.publicacao.json')
                        or (path.name.startswith(video.stem + '.')
                            and path.name.endswith('.ok'))):
                    _safe(path, root)
                    if not path.is_file():
                        raise ValueError('Comprovante não é arquivo: ' + str(path))
                    sidecars.append(path)
            confirmed = {path.name for path in sidecars}
            if all(video.stem + '.' + network + '.ok' in confirmed for network in networks):
                continue
            metadata_path = _safe(root / match[2] / (match[1] + '_' + match[3] + '.json'), root)
            metadata = (json.loads(metadata_path.read_text(encoding='utf-8'))
                        if metadata_path.exists() else {})
            rating = metadata.get('nota')
            folder = f'nota {int(rating):02d}' if isinstance(rating, (int, float)) else 'sem nota'
            target = _safe(ready / folder, root)
            sources = [*sidecars, video]
            for source in sources:
                destination = _safe(target / source.name, root)
                if destination.exists():
                    raise FileExistsError('Destino já existe: ' + str(destination))
            target.mkdir(parents=True, exist_ok=True)
            if video.stat().st_dev != target.stat().st_dev:
                raise OSError('Recuperação exige fila no mesmo sistema de arquivos.')
            for source in sidecars:
                destination = target / source.name
                os.link(source, destination)
                staged.append((source, destination))
            _move_media(video, target / video.name)
            committed = True
            recovered += 1
            for source, destination in staged:
                try:
                    source.unlink()
                except OSError as error:
                    log('Comprovante original preservado: ' + str(source) + ': ' + str(error))
            log('Publicação pendente recuperada: ' + str(target / video.name))
        except (OSError, ValueError, TypeError, AttributeError, OverflowError) as error:
            log('Recuperação adiada para ' + str(video) + ': ' + str(error))
        finally:
            if not committed:
                for source, destination in reversed(staged):
                    try:
                        # Do not remove a file replaced by another writer.
                        if destination.samefile(source):
                            destination.unlink()
                    except OSError as error:
                        log('Comprovante preservado na fila: ' + str(destination) + ': ' + str(error))
    return recovered


def confirmado_nas_redes(video, redes):
    """Whether every supplied network has durable proof (empty means True)."""
    video = Path(video)
    return all(video.with_name(video.stem + '.' + rede + '.ok').is_file()
               for rede in redes)


def selecionar_pendentes(videos, plataformas, desativadas, prontos):
    """Keep queue order, skipping clips awaiting only disabled networks.

    Fully confirmed clips remain eligible for cleanup, even when a network is
    disabled. Only direct rating-folder children of this profile's ``prontos``
    are eligible. No configured valid networks means no queue work.
    """
    networks = set(plataformas) & _NETWORKS
    if not networks:
        return []
    active = networks - set(desativadas)
    ready = Path(prontos).resolve()
    return [video for video in videos
            if Path(video).parent.parent.resolve() == ready
            and (confirmado_nas_redes(video, networks)
                 or any(not confirmado_nas_redes(video, [network]) for network in active))]
