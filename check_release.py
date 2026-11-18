"""Isolated release-core checks; no application, user settings, or live runtime imports."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import base64
import hashlib
import json
import os
import tomllib
import unittest
import zipfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from distribution import CLEAN_CONFIG, allowed, canonical_path, private_needles, scan_file
from release_builder import canonical_json, extract_baseline, signing_key, write_artifacts


class ReleaseChecks(unittest.TestCase):
    def test_safe_paths(self):
        for name in ('../bad', '/bad', 'C:/bad', '_internal/../bad', '_internal//bad',
                     '_internal/CON.txt', '_internal/file:stream', '_internal/folder./file',
                     '_internal\\file', '_internal/cookies', '_internal/file.db', 'settings.json'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                canonical_path(name)
        self.assertEqual(canonical_path('_internal/python312.dll'), '_internal/python312.dll')
        self.assertFalse(allowed(Path('_internal/backups/config.txt')))

    def test_clean_config_and_private_scan(self):
        config = tomllib.loads(CLEAN_CONFIG)
        self.assertEqual(config['canais'], [])
        self.assertEqual(config['ia']['chave'], '')
        self.assertEqual(config['marca']['texto'], '')
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'_internal').mkdir()
            (root/'_internal/canais.toml').write_text('[ia]\nchave="fixture-private-secret"\n', encoding='utf-8')
            needles = private_needles(root, root/'isolated-home')
            self.assertIn(b'fixture-private-secret', needles)
            source = root/'file'
            source.write_bytes(b'x' * (1024 * 1024 - 4) + b'fixture-private-secret')
            with self.assertRaises(RuntimeError):
                scan_file(source, 'fixture', needles)

    def test_signing_key_matches_public_config(self):
        key = Ed25519PrivateKey.generate()
        config = {'public_key': base64.b64encode(key.public_key().public_bytes_raw()).decode('ascii')}
        with patch.dict(os.environ, {'CLIPADOR_SIGNING_KEY': base64.b64encode(key.private_bytes_raw()).decode('ascii')}):
            signing_key(config).public_key().verify(key.sign(b'fixture'), b'fixture')
        for invalid in ('invalid-base64', base64.b64encode(b'x' * 31).decode('ascii'),
                        base64.b64encode(Ed25519PrivateKey.generate().private_bytes_raw()).decode('ascii')):
            with patch.dict(os.environ, {'CLIPADOR_SIGNING_KEY': invalid}), self.assertRaises(ValueError):
                signing_key(config)

    def test_manifest_signature_zip_layout_and_runtime(self):
        key = Ed25519PrivateKey.generate()
        metadata = {'generation': 1001, 'version': 'v1.0.1001', 'commit': 'a' * 40, 'runtime': 'runtime-1'}
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = {}
            names = ['Clipador.exe', 'ClipadorWorker.exe', 'ClipadorLauncher.exe',
                     'ffmpeg.exe', 'ffprobe.exe', '_internal/python312.dll', '_internal/helper.py',
                     '_internal/canais.toml', '_internal/updater-config.json', '_internal/version.json']
            for index, name in enumerate(names):
                source = root/'input'/name
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes((CLEAN_CONFIG if name.endswith('canais.toml') else f'fixture-{index}').encode('utf-8'))
                files[name] = source
            updates = [name for name in names if name not in {'ffmpeg.exe', 'ffprobe.exe', '_internal/python312.dll'}]
            output = root/'release'
            manifest = write_artifacts(files, updates, metadata, output, key, {b'fixture-secret-never-shipped'})
            data = (output/'release.json').read_bytes()
            self.assertEqual(data, canonical_json(json.loads(data)))
            signature = base64.b64decode((output/'release.sig').read_bytes())
            key.public_key().verify(signature, data)
            with self.assertRaises(InvalidSignature):
                key.public_key().verify(signature, data + b' ')
            self.assertEqual({entry['path'] for entry in manifest['files']}, set(names))
            for entry in manifest['files']:
                content = files[entry['path']].read_bytes()
                self.assertEqual(entry['sha256'], hashlib.sha256(content).hexdigest())
                self.assertEqual(entry['size'], len(content))
            for kind, expected, prefix in (('full', names, 'Clipador/'), ('update', updates, '')):
                archive = output/manifest[kind]['name']
                self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), manifest[kind]['sha256'])
                with zipfile.ZipFile(archive) as bundle:
                    self.assertIsNone(bundle.testzip())
                    self.assertEqual(set(bundle.namelist()), {prefix + name for name in expected})
                    for name in expected:
                        self.assertEqual(bundle.read(prefix + name), files[name].read_bytes())
            extracted = root/'extracted'
            extract_baseline(output/'Clipador-full.zip', extracted)
            self.assertEqual((extracted/'Clipador/_internal/python312.dll').read_bytes(), files['_internal/python312.dll'].read_bytes())
            with self.assertRaises(ValueError):
                write_artifacts(files, updates, metadata, output, key, set())
            with self.assertRaises(ValueError):
                write_artifacts(files, updates + ['_internal/python312.dll'], metadata, root/'invalid', key, set())
            self.assertFalse((root/'invalid').exists())
            collision = dict(files, **{'_internal/HELPER.py': files['_internal/helper.py']})
            with self.assertRaises(ValueError):
                write_artifacts(collision, updates, metadata, root/'collision', key, set())

    def test_baseline_rejects_traversal_and_aliases_before_extraction(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, names in enumerate((['Clipador/../escape'], ['Clipador/_internal/link'],
                                           ['Clipador/Clipador.exe', 'Clipador/clipador.exe'])):
                archive = root/f'bad-{index}.zip'
                with zipfile.ZipFile(archive, 'w') as bundle:
                    for name in names:
                        member = zipfile.ZipInfo(name)
                        if name.endswith('/link'):
                            member.create_system = 3
                            member.external_attr = 0o120777 << 16
                        bundle.writestr(member, b'fixture')
                destination = root/f'bad-{index}'
                with self.assertRaises(ValueError):
                    extract_baseline(archive, destination)
                self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main()
