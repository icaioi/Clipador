"""Signed updater filesystem/HTTP checks; never starts the application or reads user config."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import base64
import hashlib
import json
import os
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch
import urllib.parse
import urllib.request
import uuid
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from clipador_updater import Updater, UpdateCancelled, UpdateError


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')


def archive(entries, prefix=''):
    output = BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as package:
        for name, data in entries.items():
            package.writestr(prefix + name, data)
    return output.getvalue()


class ReleaseServer:
    """Only transport redirects GitHub-shaped requests; HTTP and payloads are real."""
    def __init__(self):
        self.routes = {}
        self.requests = []
        self.observe = lambda: None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests.append(self.path)
                owner.observe()
                body = owner.routes.get(self.path)
                if body is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def transport(self, request, timeout):
        remote = urllib.parse.urlsplit(request.full_url)
        if remote.scheme != 'https' or remote.netloc not in ('api.github.com', 'github.com'):
            raise AssertionError('Unexpected updater destination: ' + request.full_url)
        local = 'http://127.0.0.1:' + str(self.server.server_port) + remote.path
        return self.opener.open(urllib.request.Request(local, headers=dict(request.header_items())), timeout=timeout)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class UpdaterChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix='clipador-updater-check-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = self.root / 'LocalAppData' / 'Clipador'
        self.documents = self.root / 'Documents' / 'Clipador' / 'my-channel.toml'
        self.documents.parent.mkdir(parents=True)
        self.documents.write_bytes(b'personal channel and credentials must survive')
        self.sentinel = self.root / 'outside-sentinel.txt'
        self.sentinel.write_bytes(b'not managed by updater')
        self.key = Ed25519PrivateKey.generate()
        self.config = {
            'repository': 'fixture/Clipador', 'runtime': 'runtime-1',
            'public_key': base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode('ascii'),
        }
        self.http = ReleaseServer()
        self.addCleanup(self.http.close)
        self.updater = Updater(self.config, self.store, transport=self.http.transport)
        self.old_files = self.files(1)
        self.publish(1, self.old_files)
        bootstrap = self.root / 'bootstrap'
        bootstrap.mkdir()
        self.current = self.updater.prepare(bootstrap)
        self.assertEqual(self.updater.current(), self.current)
        self.prior_pointer = (self.store / 'current.json').read_bytes()
        self.prior_files = {p.relative_to(self.current).as_posix(): p.read_bytes()
                            for p in self.current.rglob('*') if p.is_file()}
        self.http.requests.clear()
        self.new_files = self.files(2)

    def files(self, generation):
        return {
            'Clipador.exe': ('application-' + str(generation)).encode(),
            'ClipadorWorker.exe': ('worker-' + str(generation)).encode(),
            'ClipadorLauncher.exe': ('launcher-' + str(generation)).encode(),
            '_internal/version.json': canonical({'generation': generation, 'version': 'v1.0.' + str(generation),
                                                  'commit': str(generation) * 40, 'runtime': 'runtime-1'}),
            '_internal/updater-config.json': canonical(self.config),
            '_internal/python312.dll': b'unchanged runtime fixture',
            '_internal/canais.toml': b'canais = []\n',
        }

    def publish(self, generation, files, update_zip=None, full_zip=None, mutate=None, signature=None):
        version = 'v1.0.' + str(generation)
        updates = [name for name in files if name != '_internal/python312.dll']
        delta = archive({name: files[name] for name in updates}) if update_zip is None else update_zip
        full = archive(files, 'Clipador/') if full_zip is None else full_zip
        manifest = {
            'schema': 1, 'generation': generation, 'version': version,
            'commit': str(generation) * 40, 'runtime': 'runtime-1',
            'files': [{'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                      for name, data in files.items()],
            'update_files': updates,
            'update': {'name': 'Clipador-update.zip', 'size': len(delta), 'sha256': hashlib.sha256(delta).hexdigest()},
            'full': {'name': 'Clipador-full.zip', 'size': len(full), 'sha256': hashlib.sha256(full).hexdigest()},
        }
        if mutate:
            mutate(manifest)
        payload = canonical(manifest)
        signed = base64.b64encode(self.key.sign(payload)) + b'\n' if signature is None else signature(payload)
        self.http.routes = {
            '/repos/fixture/Clipador/releases/latest': canonical({'tag_name': version}),
            '/fixture/Clipador/releases/download/' + version + '/release.json': payload,
            '/fixture/Clipador/releases/download/' + version + '/release.sig': signed,
            '/fixture/Clipador/releases/download/' + version + '/Clipador-update.zip': delta,
            '/fixture/Clipador/releases/download/' + version + '/Clipador-full.zip': full,
        }

    def assert_preserved(self):
        self.assertEqual((self.store / 'current.json').read_bytes(), self.prior_pointer)
        self.assertEqual(Updater(self.config, self.store).current(), self.current)
        self.assertEqual({p.relative_to(self.current).as_posix(): p.read_bytes()
                          for p in self.current.rglob('*') if p.is_file()}, self.prior_files)
        self.assertEqual(self.documents.read_bytes(), b'personal channel and credentials must survive')
        self.assertEqual(self.sentinel.read_bytes(), b'not managed by updater')
        self.assertFalse(list(self.store.glob('.download-*')), 'Download temporary directories leaked')
        self.assertFalse(list((self.store / 'versions').glob('.staging-*')), 'Staging directories leaked')

    @contextmanager
    def rejected(self, errors=UpdateError):
        with self.assertRaises(errors):
            yield
        self.assert_preserved()

    def test_delta_reuses_runtime_and_switches_pointer_only_after_success(self):
        self.publish(2, self.new_files)
        observations = []
        def observe():
            observations.append((self.store / 'current.json').read_bytes())
        self.http.observe = observe
        def notified(message, progress):
            if progress < 1:
                observe()
        self.updater.notify = notified
        installed = self.updater.prepare(self.current)
        self.assertTrue(observations)
        self.assertTrue(all(value == self.prior_pointer for value in observations), 'Pointer changed while preparing update')
        self.assertNotEqual(installed, self.current)
        self.assertEqual(self.updater.current(), installed)
        self.assertNotEqual((self.store / 'current.json').read_bytes(), self.prior_pointer)
        for name, data in self.new_files.items():
            self.assertEqual((installed / name).read_bytes(), data, name)
        self.assertTrue(os.path.samefile(installed / '_internal/python312.dll', self.current / '_internal/python312.dll'),
                        'Same-volume unchanged runtime was not reused by hardlink')
        self.assertTrue(any(path.endswith('/Clipador-update.zip') for path in self.http.requests))
        self.assertFalse(any(path.endswith('/Clipador-full.zip') for path in self.http.requests))
        # Success must preserve the old install and user data as well as failure does.
        saved_pointer = (self.store / 'current.json').read_bytes()
        self.assertEqual(self.documents.read_bytes(), b'personal channel and credentials must survive')
        self.assertEqual(self.sentinel.read_bytes(), b'not managed by updater')
        self.assertEqual((self.current / 'Clipador.exe').read_bytes(), b'application-1')
        self.assertEqual(Updater(self.config, self.store).current(), installed)
        self.assertEqual((self.store / 'current.json').read_bytes(), saved_pointer)

    def test_current_rejects_cached_executable_with_tampered_bytes(self):
        self.publish(2, self.new_files)
        installed = self.updater.prepare(self.current)
        pointer = (self.store / 'current.json').read_bytes()
        receipt = (installed / '.release-receipt.json').read_bytes()
        (installed / 'Clipador.exe').write_bytes(b'X' * len(self.new_files['Clipador.exe']))
        self.assertIsNone(Updater(self.config, self.store).current(),
                          'Cached executable with invalid signed digest remained launchable')
        self.assertEqual((self.store / 'current.json').read_bytes(), pointer)
        self.assertEqual((installed / '.release-receipt.json').read_bytes(), receipt)

    def test_prepare_repairs_tampered_cached_installation_despite_identical_receipt(self):
        self.publish(2, self.new_files)
        installed = self.updater.prepare(self.current)
        receipt = (installed / '.release-receipt.json').read_bytes()
        (installed / 'Clipador.exe').write_bytes(b'X' * len(self.new_files['Clipador.exe']))
        self.http.requests.clear()
        repaired = self.updater.prepare(self.current)
        self.assertEqual(repaired, installed)
        self.assertEqual((repaired / '.release-receipt.json').read_bytes(), receipt)
        for name, data in self.new_files.items():
            self.assertEqual((repaired / name).read_bytes(), data, name)
        self.assertEqual(Updater(self.config, self.store).current(), repaired)
        self.assertTrue(any(path.endswith('/Clipador-update.zip') for path in self.http.requests))
        self.assertEqual((self.current / 'Clipador.exe').read_bytes(), b'application-1')
        self.assertEqual(self.documents.read_bytes(), b'personal channel and credentials must survive')
        self.assertEqual(self.sentinel.read_bytes(), b'not managed by updater')
        self.assertFalse(list((self.store / 'versions').glob('.staging-*')))

    def test_full_package_when_unchanged_runtime_missing_or_corrupt(self):
        for mode in ('missing', 'corrupt'):
            with self.subTest(mode=mode):
                runtime = self.current / '_internal/python312.dll'
                if mode == 'missing':
                    runtime.unlink()
                else:
                    runtime.write_bytes(b'broken runtime')
                self.publish(2, self.new_files)
                self.http.requests.clear()
                installed = self.updater.prepare(self.current)
                self.assertEqual((installed / '_internal/python312.dll').read_bytes(), b'unchanged runtime fixture')
                self.assertEqual(self.updater.current(), installed)
                self.assertTrue(any(path.endswith('/Clipador-full.zip') for path in self.http.requests))
                self.assertFalse(any(path.endswith('/Clipador-update.zip') for path in self.http.requests))

    def test_invalid_signatures_do_not_download_or_install_payload(self):
        foreign = Ed25519PrivateKey.generate()
        for signature in (lambda payload: b'not-base64!', lambda payload: base64.b64encode(bytes(64)),
                          lambda payload: base64.b64encode(foreign.sign(payload))):
            with self.subTest(signature=signature), self.rejected():
                self.publish(2, self.new_files, signature=signature)
                self.http.requests.clear()
                try:
                    self.updater.prepare(self.current)
                finally:
                    self.assertFalse(any(path.endswith('.zip') for path in self.http.requests))

    def test_tampered_signed_manifest_is_rejected(self):
        self.publish(2, self.new_files)
        path = '/fixture/Clipador/releases/download/v1.0.2/release.json'
        self.http.routes[path] = self.http.routes[path].replace(b'application', b'Application') + b' '
        with self.rejected():
            self.updater.prepare(self.current)

    def test_download_zip_hash_mismatch_is_rejected(self):
        self.publish(2, self.new_files)
        path = '/fixture/Clipador/releases/download/v1.0.2/Clipador-update.zip'
        payload = bytearray(self.http.routes[path])
        payload[-1] ^= 1
        self.http.routes[path] = bytes(payload)
        with self.rejected():
            self.updater.prepare(self.current)

    def test_signed_zip_with_corrupt_file_is_rejected(self):
        entries = {name: data for name, data in self.new_files.items() if name != '_internal/python312.dll'}
        entries['Clipador.exe'] = b'X' * len(entries['Clipador.exe'])
        self.publish(2, self.new_files, update_zip=archive(entries))
        with self.rejected():
            self.updater.prepare(self.current)

    def test_signed_non_zip_is_rejected_without_changing_installation(self):
        self.publish(2, self.new_files, update_zip=b'not a zip archive')
        with self.rejected((UpdateError, zipfile.BadZipFile)):
            self.updater.prepare(self.current)

    def test_zip_traversal_and_windows_aliases_are_rejected(self):
        unsafe = ('../outside-sentinel.txt', '_internal/../../outside-sentinel.txt',
                  '/outside-sentinel.txt', 'C:/outside-sentinel.txt', '_internal\\evil.dll',
                  '_internal/CON.txt', '_internal/aux.dll', '_internal/COM1.py',
                  '_internal/LPT9.txt', '_internal/NUL/runtime.dll', '_internal/file:stream',
                  '_internal/folder./runtime.dll', '_internal/runtime.dll ')
        for name in unsafe:
            with self.subTest(path=name):
                entries = {path: data for path, data in self.new_files.items() if path != '_internal/python312.dll'}
                entries.pop('_internal/canais.toml')
                entries[name] = b'canais = []\n'
                self.publish(2, self.new_files, update_zip=archive(entries))
                with self.rejected():
                    self.updater.prepare(self.current)

    def check_device_name(self, name):
        files = dict(self.new_files)
        files[name] = b'invalid Windows filename'
        self.publish(2, files)
        with self.rejected():
            self.updater.prepare(self.current)

    def test_signed_manifest_console_device_is_rejected(self):
        self.check_device_name('_internal/CON.txt')

    def test_signed_manifest_aux_device_is_rejected(self):
        self.check_device_name('_internal/aux.dll')

    def test_signed_manifest_serial_device_is_rejected(self):
        self.check_device_name('_internal/COM1.py')

    def test_signed_manifest_printer_device_is_rejected(self):
        self.check_device_name('_internal/LPT9.txt')

    def test_signed_manifest_null_device_directory_is_rejected(self):
        self.check_device_name('_internal/NUL/runtime.dll')

    def test_signed_manifest_superscript_device_is_rejected(self):
        self.check_device_name('_internal/COM\u00b9.txt')

    def test_cancel_during_real_download_preserves_prior_installation(self):
        self.new_files['Clipador.exe'] = b'new executable bytes' * 150000
        self.publish(2, self.new_files)
        cancelled = threading.Event()
        self.updater.cancel = cancelled.is_set
        def notified(message, progress):
            if .1 < progress < .65:
                cancelled.set()
        self.updater.notify = notified
        with self.rejected(UpdateCancelled):
            self.updater.prepare(self.current)
        self.assertTrue(cancelled.is_set(), 'Cancellation was not exercised during download')


@unittest.skipUnless(os.name == 'nt', 'Windows launch error reporting')
class LauncherStartChecks(unittest.TestCase):
    def test_policy_block_is_reported_without_retry_or_lost_mutex(self):
        import clipador_launcher as launcher
        for log_writable in (True, False):
            with self.subTest(log_writable=log_writable), TemporaryDirectory() as temporary:
                folder = Path(temporary)
                internal = folder/'_internal'
                internal.mkdir()
                repository = 'fixture/blocked-' + uuid.uuid4().hex
                public = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
                (internal/'updater-config.json').write_text(json.dumps({
                    'repository': repository, 'public_key': base64.b64encode(public).decode(),
                    'runtime': 'fixture',
                }), encoding='utf-8')
                # No real program is launched and no existing profile is read.
                profile = folder/'Documents'/'Clipador'/'canais.toml'
                profile.parent.mkdir(parents=True)
                profile.write_bytes(b'local-profile-must-not-change')
                blocked = OSError('Uma política de Controle de Aplicativo bloqueou este arquivo')
                blocked.winerror = 4551
                with patch.object(launcher.sys, 'executable', str(folder/'ClipadorLauncher.exe')), \
                     patch.dict(os.environ, {'LOCALAPPDATA': str(folder/'local')}), \
                     patch.object(launcher.subprocess, 'Popen', side_effect=blocked) as start, \
                     patch.object(launcher.ctypes.windll.user32, 'MessageBoxW', return_value=1) as notice:
                    if log_writable:
                        result = launcher.main(['--managed', '--ready', '--teste'])
                    else:
                        with patch.object(Path, 'mkdir', side_effect=PermissionError('log denied')):
                            result = launcher.main(['--managed', '--ready', '--teste'])
                self.assertEqual(result, 1, 'A blocked application must not report successful startup')
                self.assertEqual(start.call_count, 1, 'Do not retry a blocked executable through another path')
                self.assertEqual(notice.call_count, 1)
                message = notice.call_args.args[1]
                self.assertIn('4551', message)
                self.assertIn(str(folder/'Clipador.exe'), message)
                self.assertEqual(profile.read_bytes(), b'local-profile-must-not-change')
                identifier = hashlib.sha256(repository.encode()).hexdigest()[:16]
                mutex = launcher._Mutex('Local\\Clipador-' + identifier)
                try:
                    self.assertTrue(mutex.owned, 'Failed startup left the launcher permanently locked')
                finally:
                    mutex.close()
                if log_writable:
                    diagnostic = folder/'local'/'Clipador'/'updates'/identifier/'updater.log'
                    self.assertIn('4551', diagnostic.read_text(encoding='utf-8'))


@unittest.skipUnless(os.name == 'nt', 'Windows named mutex semantics')
class LauncherMutexChecks(unittest.TestCase):
    def test_duplicate_acquisition_from_real_subprocess(self):
        from clipador_launcher import _Mutex
        name = 'Local\\Clipador-QA-' + uuid.uuid4().hex
        mutex = _Mutex(name)
        self.addCleanup(mutex.close)
        self.assertTrue(mutex.owned)
        code = ('from clipador_launcher import _Mutex; import sys; '
                'mutex=_Mutex(sys.argv[1]); print(int(mutex.owned)); mutex.close()')
        def acquired():
            result = subprocess.run([sys.executable, '-c', code, name], cwd=Path(__file__).resolve().parent,
                                    capture_output=True, text=True, timeout=15, check=True)
            return result.stdout.strip()
        self.assertEqual(acquired(), '0', 'Second process acquired an already-owned launcher mutex')
        mutex.close()
        self.assertEqual(acquired(), '1', 'Launcher mutex remained locked after owner closed it')


if __name__ == '__main__':
    unittest.main(verbosity=2)
