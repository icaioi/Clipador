"""Check real PE manifests, archives and isolated frozen updater long-path I/O.

Run after the installed baseline has been extracted into CLIPADOR_RUNTIME_ROOT:
    python check_package.py
Optional positional EXEs additionally check the final packaged release artifacts.
No application UI is launched: the isolated probe replaces its frozen entry.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
from xml.dom import minidom
import zlib
import zipfile

from package import Package, ROOT, archive, manifest_long_path_aware, read_application_manifests

def check_executable(path):
    manifests = read_application_manifests(path)
    if not manifests:
        raise ValueError(f'{path.name}: missing executable application manifest')
    for language, data in manifests.items():
        if not manifest_long_path_aware(data):
            raise ValueError(f'{path.name}: longPathAware is not true in language {language}')
    prefix, entries, version, library = archive(path.read_bytes())
    if not prefix.startswith(b'MZ') or not entries or version != 312 or not library.rstrip(b'\0'):
        raise ValueError(f'{path.name}: invalid frozen executable archive')
    for name, compressed, kind, raw_size, data in entries:
        unpacked = zlib.decompress(data) if compressed else data
        if len(unpacked) != raw_size:
            raise ValueError(f'{path.name}: CArchive entry size mismatch')
    print(f'{path.name}: longPathAware=true ({len(manifests)} language(s)); CArchive intact')


def manifest_settings(data):
    """Compare existing XML semantics, ignoring only the added long-path setting."""
    document = minidom.parseString(data)
    def signature(node):
        if node.nodeType == node.ELEMENT_NODE:
            name = (node.namespaceURI, node.localName)
            if name == ('http://schemas.microsoft.com/SMI/2016/WindowsSettings', 'longPathAware'):
                return None
            attributes = tuple(sorted(
                ((attribute.namespaceURI or '', attribute.localName), attribute.value)
                for attribute in node.attributes.values()
                if attribute.namespaceURI != 'http://www.w3.org/2000/xmlns/'))
            children = tuple(value for child in node.childNodes
                             if (value := signature(child)) is not None)
            if (not attributes and not children and name[0] == 'urn:schemas-microsoft-com:asm.v3'
                    and name[1] in ('application', 'windowsSettings')):
                return None
            return name, attributes, children
        if node.nodeType in (node.TEXT_NODE, node.CDATA_SECTION_NODE) and node.data.strip():
            return node.data.strip()
        return None
    try:
        return signature(document.documentElement)
    finally:
        document.unlink()


def check_frozen_long_paths():
    if os.name != 'nt':
        raise OSError('The real frozen long-path probe requires Windows')
    runtime = ROOT/'_internal'
    if not runtime.is_dir():
        raise FileNotFoundError('Extract the baseline runtime into CLIPADOR_RUNTIME_ROOT before this check')
    original = read_application_manifests(ROOT/'Clipador.exe')
    temporary = tempfile.mkdtemp(prefix='clipador-frozen-path-')
    try:
        folder = Path(temporary)
        # A directory junction avoids copying the private runtime or touching the
        # installed application. The child only executes our replacement entry.
        subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J',
                        str(folder/'_internal'), str(runtime.resolve())],
                       capture_output=True, check=True, timeout=30,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        target = folder/'cache'
        while len(str(target)) <= 320:
            target /= 'long-path-segment-0123456789'
        marker = target/'_internal'/'probe'/'frozen-marker.txt'
        reused = target.with_name(target.name+'-reused')
        payload = b'frozen-updater-long-path-write-ok'
        records = [{'path': '_internal/probe/frozen-marker.txt',
                    'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}]
        (folder/'records.json').write_text(json.dumps(records), encoding='utf-8')
        with zipfile.ZipFile(folder/'payload.zip', 'w') as archive_file:
            archive_file.writestr(records[0]['path'], payload)
        entry = """
import json, sys
from pathlib import Path
source, folder, target, reused = map(Path, sys.argv[1:])
sys.path.insert(0, str(source))
import clipador_updater as updater_module
assert Path(updater_module.__file__).resolve() == (source/'clipador_updater.py').resolve(), 'Probe must load the source updater'
def deny_network(*args, **kwargs):
    raise AssertionError('Frozen updater probe must never access the network')
config = json.loads((source/'updater-config.json').read_text(encoding='utf-8'))
updater = updater_module.Updater(config, folder/'store', transport=deny_network)
records = json.loads((folder/'records.json').read_text(encoding='utf-8'))
updater._extract(folder/'payload.zip', target, records)
assert updater._inventory_valid(target, records), 'Extracted deep inventory is invalid'
assert updater._reuse(target, reused, records), 'Deep runtime reuse failed'
assert updater._inventory_valid(reused, records), 'Reused deep inventory is invalid'
(folder/'probe-complete.txt').write_text('ok', encoding='utf-8')
"""
        probe = folder/'ClipadorLongPathCheck.exe'
        probe.write_bytes(Package('Clipador.exe').build(entry=entry))
        check_executable(probe)
        updated = read_application_manifests(probe)
        if original:
            if original.keys() != updated.keys():
                raise AssertionError('Application manifest languages changed')
            for language in original:
                if manifest_settings(original[language]) != manifest_settings(updated[language]):
                    raise AssertionError('Existing manifest settings changed (including execution level/DPI)')
        result = subprocess.run([str(probe), str(Path(__file__).resolve().parent),
                                 str(folder), str(target), str(reused)],
                                cwd=folder, capture_output=True, timeout=60,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode != 0:
            raise AssertionError(f'Frozen long-path probe failed with exit code {result.returncode}')
        for destination in (marker, reused/'_internal'/'probe'/'frozen-marker.txt'):
            extended = Path('\\\\?\\'+str(destination))
            if not extended.is_file() or extended.read_bytes() != payload:
                raise AssertionError('Frozen updater did not write the genuine >260-character-path marker')
        if (folder/'probe-complete.txt').read_text(encoding='utf-8') != 'ok':
            raise AssertionError('Frozen updater did not complete inventory and reuse checks')
        print(f'Frozen updater extract/inventory/reuse: passed ({len(str(marker))} characters); existing manifest settings preserved')
    finally:
        junction = Path(temporary)/'_internal'
        if junction.is_dir():
            junction.rmdir()
        shutil.rmtree(Path('\\\\?\\'+temporary))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executables', nargs='*', type=Path)
    args = parser.parse_args()
    for path in args.executables:
        check_executable(path)

    check_frozen_long_paths()

if __name__ == '__main__':
    main()
