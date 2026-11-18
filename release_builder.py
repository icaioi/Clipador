"""Build signed clean releases from CLIPADOR_RUNTIME_ROOT, never a live installation.

CLI: python release_builder.py --generation INT --commit SHA --output DIR
Requires Python 3.12, bytecode==0.19.2 and cryptography==46.0.3.
The output directory must not exist. All four artifacts appear together on success.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse
import base64
import hashlib
import json
import marshal
import os
import re
import shutil
import stat
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from distribution import CLEAN_CONFIG, canonical_path, private_needles, resources, scan, scan_file

HERE = Path(__file__).resolve().parent
ARTIFACTS = ('Clipador-full.zip', 'Clipador-update.zip', 'release.json', 'release.sig')


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')


def file_record(path, name=None):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': name or path.name, 'size': path.stat().st_size, 'sha256': digest}


def extract_baseline(archive_path, destination):
    """Extract a hash-verified baseline only after checking every member."""
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Baseline destination already exists')
    with zipfile.ZipFile(archive_path) as archive:
        seen = set()
        members = []
        for member in archive.infolist():
            name = member.filename
            if member.is_dir():
                # Directories are unnecessary and must still remain under the app root.
                relative = name.rstrip('/')
                if relative != 'Clipador':
                    canonical_path(relative.removeprefix('Clipador/') + '/directory-check')
                if not name.startswith('Clipador/'):
                    raise ValueError('Unexpected baseline directory')
                continue
            if not name.startswith('Clipador/'):
                raise ValueError('Baseline must have exactly one Clipador root')
            relative = canonical_path(name[len('Clipador/'):])
            if relative.casefold() in seen or stat.S_IFMT(member.external_attr >> 16) not in (0, stat.S_IFREG):
                raise ValueError('Duplicate or non-regular baseline member')
            seen.add(relative.casefold())
            members.append((member, relative))
        required = {'clipador.exe', 'clipadorworker.exe', 'ffmpeg.exe', 'ffprobe.exe', '_internal/canais.toml'}
        if not required.issubset(seen):
            raise ValueError('Incomplete baseline')
        destination.mkdir(parents=True)
        for member, relative in members:
            target = destination/'Clipador'/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)


def signing_key(config):
    # Do not include decoded input or exception details in errors/logs.
    try:
        raw = base64.b64decode(os.environ['CLIPADOR_SIGNING_KEY'], validate=True)
        key = Ed25519PrivateKey.from_private_bytes(raw)
        public = base64.b64decode(config['public_key'], validate=True)
        if len(public) != 32 or key.public_key().public_bytes_raw() != public:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError('Missing, invalid, or mismatched release signing key') from None
    return key


def write_artifacts(files, update_files, metadata, output, key, needles):
    """Write complete manifests and two ZIP layouts from explicit safe file mappings."""
    seen = set()
    for name, source in files.items():
        canonical_path(name)
        if name.casefold() in seen:
            raise ValueError('Case-insensitive installation path collision')
        seen.add(name.casefold())
        if not source.is_file() or source.is_symlink():
            raise ValueError('Missing or linked release file')
        scan_file(source, name, needles)
    if len(update_files) != len(set(update_files)) or not set(update_files).issubset(files):
        raise ValueError('Invalid update file inventory')
    for name in update_files:
        if name not in {'Clipador.exe', 'ClipadorWorker.exe', 'ClipadorLauncher.exe',
                        '_internal/canais.toml', '_internal/updater-config.json', '_internal/version.json'}:
            if not re.fullmatch(r'_internal/[A-Za-z_][A-Za-z_0-9]*\.py', name):
                raise ValueError('Non-app file in delta')
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Release output must not already exist')
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.clipador-release-', dir=output.parent) as temporary:
        stage = Path(temporary)/'artifacts'
        stage.mkdir()
        for archive_name, names, prefix in (
                ('Clipador-full.zip', sorted(files), 'Clipador/'),
                ('Clipador-update.zip', sorted(update_files), '')):
            with zipfile.ZipFile(stage/archive_name, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for name in names:
                    archive.write(files[name], prefix + name)
        manifest = dict(metadata, schema=1,
                        files=[file_record(files[name], name) for name in sorted(files)],
                        update_files=sorted(update_files))
        for kind in ('full', 'update'):
            record = file_record(stage/f'Clipador-{kind}.zip')
            record['name'] = record.pop('path')
            manifest[kind] = record
        data = canonical_json(manifest)
        signature = key.sign(data)
        key.public_key().verify(signature, data)
        (stage/'release.json').write_bytes(data)
        (stage/'release.sig').write_bytes(base64.b64encode(signature) + b'\n')
        os.replace(stage, output)
    return manifest


def build_release(generation, commit, output):
    if generation <= 0 or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Generation must be positive and commit must be a full lowercase SHA')
    runtime_root = os.environ.get('CLIPADOR_RUNTIME_ROOT')
    if not runtime_root:
        raise ValueError('CLIPADOR_RUNTIME_ROOT must select an isolated baseline')
    root = Path(runtime_root).resolve()
    config = json.loads((HERE/'updater-config.json').read_text(encoding='utf-8'))
    if (set(config) != {'repository', 'public_key', 'runtime'}
            or config['repository'] != 'icaioi/Clipador' or config['runtime'] != 'runtime-1'):
        raise ValueError('Unexpected public updater configuration')
    key = signing_key(config)
    from package import Package, ROOT
    from integrate import all_transforms, RUNTIME_HELPERS
    if Path(ROOT).resolve() != root:
        raise ValueError('Package runtime root does not match isolated baseline')
    helpers = tuple(RUNTIME_HELPERS)
    if not helpers or len(helpers) != len(set(helpers)):
        raise ValueError('Invalid runtime helpers')
    for name in helpers:
        if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*\.py', name):
            raise ValueError('Unsafe helper name')
    metadata = {'generation': generation, 'version': f'v1.0.{generation}',
                'commit': commit, 'runtime': config['runtime']}
    needles = private_needles(root)
    transforms = all_transforms()
    files = {relative.as_posix(): source for source, relative in resources(root)}
    with TemporaryDirectory(prefix='clipador-app-build-') as temporary:
        stage = Path(temporary)

        def generated(name, data):
            scan(data, name, needles)
            target = stage/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            files[name] = target

        for name in ('Clipador.exe', 'ClipadorWorker.exe'):
            package = Package(name)
            for module in package.toc:
                if module.startswith('clipador'):
                    code = package.module(module)
                    if module in transforms:
                        code = transforms[module](code)
                    scan(marshal.dumps(code), name + ':' + module, needles)
            generated(name, package.build(transforms))
        generated('ClipadorLauncher.exe', Package('Clipador.exe').build(
            transforms, entry='from clipador_launcher import main\nraise SystemExit(main())\n'))
        for name in helpers:
            generated('_internal/' + name, (HERE/name).read_bytes())
        generated('_internal/canais.toml', CLEAN_CONFIG.encode('utf-8'))
        generated('_internal/updater-config.json', canonical_json(config))
        generated('_internal/version.json', canonical_json(metadata))
        update_files = ['Clipador.exe', 'ClipadorWorker.exe', 'ClipadorLauncher.exe',
                        '_internal/canais.toml', '_internal/updater-config.json', '_internal/version.json']
        update_files.extend('_internal/' + name for name in helpers)
        manifest = write_artifacts(files, update_files, metadata, output, key, needles)
    print(json.dumps({'version': metadata['version'], 'output': str(output),
                      'artifacts': list(ARTIFACTS), 'files': len(manifest['files']),
                      'update_files': len(update_files)}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generation', type=int, required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build_release(args.generation, args.commit, args.output)


if __name__ == '__main__':
    main()
