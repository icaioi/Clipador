"""Side-effect-free clean distribution rules shared by manual and CI packaging."""
from pathlib import Path, PurePosixPath
import os
import re
import tomllib

CLEAN_CONFIG = '''canais = []

[binarios]
ffmpeg = ""
ffprobe = ""
streamlink = ""

[legenda]
backend = "faster-whisper"
modelo = "small"
compute_type = "int8"
cpu_threads = 2
idioma = "pt"

[fila]
trabalhadores = 1

[parametros]
jogo = ""
hashtags = ""

[ia]
ativo = true
modelo = "gemini-flash-lite-latest"
nota_minima = 6
chave = ""

[marca]
texto = ""
'''
BLOCKED = {'__pycache__', '.links', 'perfil_navegador', 'clipes', 'buffer', 'backups',
           'cookies', 'local state', 'login data', 'history', 'preferences', 'secure preferences',
           'user data', 'session storage', 'local storage', 'sessions', 'crashpad', 'crash reports',
           '.env', 'licenca.json', 'config_app.json', 'primeiros_passos.json'}
BLOCKED_SUFFIXES = {'.log', '.pyc', '.pyo', '.db', '.sqlite', '.sqlite3', '.dmp'}


def private_needles(root, home=None, *, include_home=True):
    """Collect configured secrets; optionally add the current host's home heuristic."""
    home = Path.home() if home is None else Path(home)
    strings = {str(home), str(home).replace('\\', '/')} if include_home else set()

    def collect(value, key=''):
        if isinstance(value, dict):
            for k, v in value.items():
                collect(v, k)
        elif isinstance(value, list):
            for child in value:
                collect(child, key)
        elif isinstance(value, str) and len(value) >= 8 and (
                re.search(r'chave|token|senha|password|secret|api.?key|email', key, re.I)
                or key in {'marca_texto', 'texto_no_video', 'mencoes', 'hashtags_obrigatorias'}):
            strings.add(value)

    for config in (home/'Documents'/'Clipador'/'canais.toml', Path(root)/'_internal'/'canais.toml'):
        if config.is_file():
            collect(tomllib.loads(config.read_text(encoding='utf-8')))
    return {text.encode(encoding) for text in strings for encoding in ('utf-8', 'utf-16le')}


def scan(data, label, needles):
    if any(needle in data for needle in needles):
        raise RuntimeError('Private configuration or personal path detected in ' + label)


def scan_file(source, label, needles):
    overlap = max(map(len, needles), default=1) - 1
    with source.open('rb') as file:
        tail = b''
        while chunk := file.read(1024 * 1024):
            data = tail + chunk
            scan(data, label, needles)
            tail = data[-overlap:] if overlap else b''


def allowed(path):
    path = PurePosixPath(path)
    return not any(part.casefold() in BLOCKED or part.casefold().startswith('backup-')
                   for part in path.parts) and path.suffix.casefold() not in BLOCKED_SUFFIXES


def canonical_path(name):
    """Reject ZIP aliases, Windows devices, links' escape names, and user-file paths."""
    path = PurePosixPath(name)
    if (not name or '\\' in name or path.is_absolute() or path.as_posix() != name
            or any(part in {'.', '..'} or part.endswith((' ', '.'))
                   or re.search(r'[<>:"|?*\x00-\x1f]', part)
                   or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I)
                   for part in path.parts)
            or not allowed(path)):
        raise ValueError('Unsafe distribution path: ' + name)
    if name not in {'Clipador.exe', 'ClipadorWorker.exe', 'ClipadorLauncher.exe', 'ffmpeg.exe', 'ffprobe.exe'}:
        if len(path.parts) < 2 or path.parts[0] != '_internal':
            raise ValueError('Unexpected installation path: ' + name)
    return name


def resources(root):
    """Yield only program resources; never follow directory links or user-data trees."""
    root = Path(root)
    internal = root/'_internal'
    if not internal.is_dir() or internal.is_symlink() or internal.is_junction():
        raise RuntimeError('Missing or linked _internal runtime directory')
    for folder, dirs, files in os.walk(internal, followlinks=False):
        base = Path(folder)
        dirs[:] = [name for name in dirs if allowed(base.relative_to(root)/name)
                   and not (base/name).is_symlink() and not (base/name).is_junction()]
        for name in files:
            file = base/name
            relative = file.relative_to(root)
            if relative.as_posix() == '_internal/canais.toml' or not allowed(relative):
                continue
            if file.is_symlink() or not file.resolve().is_relative_to(internal.resolve()):
                raise RuntimeError('External resource link refused: ' + str(relative))
            yield file, relative
    for name in ('ffmpeg.exe', 'ffprobe.exe'):
        file = root/name
        if not file.is_file() or file.is_symlink():
            raise RuntimeError(name + ' missing or linked')
        yield file, Path(name)
