"""Isolated filesystem checks: python check_pending.py (no posting/config)."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import unittest

import clipador_pending
from clipador_pending import recuperar_pendentes, confirmado_nas_redes, selecionar_pendentes


class PendingRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix='clipador-pending-')
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.root = self.home / 'clipes'
        self.failed = self.root / 'falhou_postar' / 'perfil secundario'
        self.ready = self.root / 'PRONTOS PARA POSTAR' / 'perfil secundario'
        self.logs = []

    def clip(self, label='canal_com_underscores', rating=8):
        video = self.failed / (label + '_2026-11-20_10-43-51.mp4')
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b'video-' + label.encode())
        metadata = self.root / '2026-11-20' / (label + '_10-43-51.json')
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text(json.dumps({'nota': rating, 'perfil': 'perfil secundario'}), encoding='utf-8')
        return video, metadata

    def queued_clip(self, label):
        video, metadata = self.clip(label)
        target = self.ready / 'nota 08' / video.name
        target.parent.mkdir(parents=True, exist_ok=True)
        video.rename(target)
        return target, metadata

    def sidecar(self, video, suffix, data=b'proof'):
        path = video.with_name(video.stem + suffix)
        path.write_bytes(data)
        return path

    def recover(self, networks=('instagram', 'tiktok')):
        return recuperar_pendentes(self.root, self.failed, self.ready, networks, self.logs.append)

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()}

    def test_partial_confirmation_survives_and_only_missing_network_is_eligible(self):
        video, metadata = self.clip()
        sidecars = [self.sidecar(video, suffix, suffix.encode()) for suffix in
                    ('.txt', '.instagram.ok', '.youtube.ok', '.custom.ok', '.publicacao.json')]
        original = self.root / '2026-11-20' / 'canal_com_underscores_10-43-51.bruto.mp4'
        original.write_bytes(b'raw-original')
        original_bytes = {path.name: path.read_bytes() for path in [video, *sidecars]}
        move = clipador_pending._move_media

        def publish(source, destination):
            self.assertFalse(destination.exists())
            self.assertTrue(source.exists())
            for sidecar in sidecars:
                self.assertEqual((destination.parent / sidecar.name).read_bytes(), sidecar.read_bytes())
            move(source, destination)

        with patch.object(clipador_pending, '_move_media', side_effect=publish):
            self.assertEqual(self.recover(), 1)
        queued = self.ready / 'nota 08' / video.name
        self.assertEqual({path.name: path.read_bytes() for path in queued.parent.iterdir()}, original_bytes)
        self.assertFalse(video.exists())
        self.assertTrue(all(not path.exists() for path in sidecars))
        missing = [network for network in ('instagram', 'tiktok')
                   if not queued.with_name(queued.stem + '.' + network + '.ok').is_file()]
        self.assertEqual(missing, ['tiktok'])
        self.assertEqual(original.read_bytes(), b'raw-original')
        self.assertTrue(metadata.exists())
        self.assertFalse((self.root / 'PRONTOS PARA POSTAR' / 'nota 08').exists())
        before = self.snapshot()
        self.assertEqual(self.recover(), 0)
        self.assertEqual(self.snapshot(), before)

    def test_no_valid_networks_do_not_touch_files(self):
        self.clip()
        before = self.snapshot()
        for networks in ([], ['unknown']):
            self.assertEqual(self.recover(networks), 0)
            self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.ready.exists())

    def test_fully_confirmed_and_unknown_files_remain_untouched(self):
        video, _ = self.clip()
        for network in ('instagram', 'tiktok'):
            self.sidecar(video, '.' + network + '.ok')
        (self.failed / 'unrelated.mp4').write_bytes(b'unrelated')
        (self.failed / 'notes.json').write_text('{}', encoding='utf-8')
        original = self.failed / (video.stem + '.vertical.mp4')
        original.write_bytes(b'original')
        before = self.snapshot()
        self.assertEqual(self.recover(), 0)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.ready.exists())

    def test_missing_rating_uses_sem_nota(self):
        video, metadata = self.clip(rating=None)
        metadata.unlink()
        self.assertEqual(self.recover(['tiktok', 'invalid']), 1)
        self.assertTrue((self.ready / 'sem nota' / video.name).is_file())

    def test_destination_media_and_sidecar_collisions_preserve_every_byte(self):
        for suffix in ('.mp4', '.instagram.ok', '.txt', '.publicacao.json', '.custom.ok'):
            with self.subTest(suffix=suffix):
                video, _ = self.clip('collision_' + suffix.replace('.', '_'))
                for sidecar in ('.instagram.ok', '.txt', '.publicacao.json', '.custom.ok'):
                    self.sidecar(video, sidecar)
                target = self.ready / 'nota 08'
                target.mkdir(parents=True, exist_ok=True)
                destination = target / (video.stem + suffix)
                destination.write_bytes(b'existing-must-not-change')
                before = self.snapshot()
                self.assertEqual(self.recover(), 0)
                self.assertEqual(self.snapshot(), before)
                self.assertTrue(video.exists())
        self.assertTrue(self.logs)

    def test_error_staging_sidecars_rolls_back_without_exposing_video(self):
        video, _ = self.clip()
        self.sidecar(video, '.instagram.ok')
        self.sidecar(video, '.txt')
        before = self.snapshot()
        link = os.link
        calls = 0

        def fail_second_link(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('injected sidecar staging failure')
            return link(source, destination)

        with patch.object(clipador_pending.os, 'link', side_effect=fail_second_link):
            self.assertEqual(self.recover(), 0)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.ready / 'nota 08' / video.name).exists())
        self.assertEqual(self.recover(), 1)

    def test_media_move_failure_keeps_all_source_data(self):
        video, _ = self.clip()
        self.sidecar(video, '.instagram.ok')
        self.sidecar(video, '.txt')
        before = self.snapshot()
        with patch.object(clipador_pending, '_move_media', side_effect=OSError('move denied')):
            self.assertEqual(self.recover(), 0)
        self.assertEqual(self.snapshot(), before)

    def test_paths_outside_root_and_overlapping_folders_are_rejected(self):
        self.clip()
        before = self.snapshot()
        for failed, ready in ((self.home / 'outside', self.ready),
                              (self.failed, self.home / 'outside'),
                              (self.failed, self.failed / 'queue'),
                              (self.failed, self.failed.parent)):
            with self.subTest(failed=failed, ready=ready):
                with self.assertRaises(ValueError):
                    recuperar_pendentes(self.root, failed, ready, ['tiktok'], self.logs.append)
        self.assertEqual(self.snapshot(), before)

    def test_principal_recovery_never_traverses_named_profile_subfolders(self):
        named, metadata = self.clip('named_profile', rating=9)
        proof = self.sidecar(named, '.instagram.ok', b'named-instagram-proof')
        caption = self.sidecar(named, '.txt', b'named-caption')
        receipt = self.sidecar(named, '.publicacao.json', b'named-receipt')
        named_files = [named, metadata, proof, caption, receipt]
        before = {path: path.read_bytes() for path in named_files}
        principal_failed = self.failed.parent
        principal_ready = self.ready.parent
        principal = principal_failed / 'principal_2026-11-20_11-00-00.mp4'
        principal.write_bytes(b'principal-video')
        self.assertEqual(recuperar_pendentes(self.root, principal_failed, principal_ready,
                                            ['instagram', 'tiktok'], self.logs.append), 1)
        self.assertEqual({path: path.read_bytes() for path in named_files}, before)
        self.assertFalse((principal_ready / 'nota 09' / named.name).exists())
        self.assertFalse(self.ready.exists())
        principal_queued = principal_ready / 'sem nota' / principal.name
        self.assertEqual(principal_queued.read_bytes(), b'principal-video')
        self.assertEqual(self.recover(), 1)
        queued = self.ready / 'nota 09' / named.name
        self.assertEqual(queued.read_bytes(), before[named])
        for source in (proof, caption, receipt):
            self.assertEqual((queued.parent / source.name).read_bytes(), before[source])
            self.assertFalse(source.exists())
        self.assertFalse(named.exists())
        self.assertEqual(metadata.read_bytes(), before[metadata])
        self.assertEqual(principal_queued.read_bytes(), b'principal-video')
        self.assertEqual(self.recover(), 0)

    def test_disabled_only_pending_does_not_starve_later_active_work(self):
        waiting, _ = self.queued_clip('first_waiting')
        later, _ = self.queued_clip('second_active')
        self.sidecar(waiting, '.instagram.ok')
        self.sidecar(later, '.tiktok.ok')
        before = self.snapshot()
        networks = ['instagram', 'tiktok']
        self.assertEqual(selecionar_pendentes([waiting, later], networks, ['tiktok'], self.ready), [later])
        self.assertEqual(selecionar_pendentes([waiting, later], networks, [], self.ready), [waiting, later])
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(waiting.exists())

    def test_fully_confirmed_cleanup_is_selected_with_disabled_networks(self):
        waiting, _ = self.queued_clip('first_blocked')
        complete, _ = self.queued_clip('second_complete')
        later, _ = self.queued_clip('third_active')
        self.sidecar(waiting, '.instagram.ok')
        for network in ('instagram', 'tiktok'):
            self.sidecar(complete, '.' + network + '.ok')
        before = self.snapshot()
        videos = [waiting, complete, later]
        networks = ['instagram', 'tiktok']
        self.assertEqual(selecionar_pendentes(videos, networks, ['tiktok'], self.ready), [complete, later])
        self.assertEqual(selecionar_pendentes(videos, networks, networks, self.ready), [complete])
        self.assertEqual(selecionar_pendentes(videos, [], [], self.ready), [])
        self.assertEqual(self.snapshot(), before)

    def test_selection_excludes_other_profiles_in_both_directions(self):
        named, _ = self.queued_clip('named_queued')
        principal_ready = self.ready.parent
        principal = principal_ready / 'sem nota' / 'principal_2026-11-20_11-00-00.mp4'
        principal.parent.mkdir(parents=True, exist_ok=True)
        principal.write_bytes(b'principal-video')
        self.sidecar(named, '.instagram.ok')
        before = self.snapshot()
        # Simulate the recursive principal scanner returning both profiles.
        videos = [named, principal]
        networks = ['instagram', 'tiktok']
        self.assertEqual(selecionar_pendentes(videos, networks, [], principal_ready), [principal])
        self.assertEqual(selecionar_pendentes(videos, networks, [], self.ready), [named])
        self.sidecar(named, '.tiktok.ok')
        self.assertEqual(selecionar_pendentes(videos, networks, ['tiktok'], principal_ready), [principal])
        self.assertEqual(selecionar_pendentes(videos, networks, ['tiktok'], self.ready), [named])
        named.with_name(named.stem + '.tiktok.ok').unlink()
        self.assertEqual(self.snapshot(), before)

    def test_disabled_network_confirmation_requires_its_existing_proof(self):
        video, _ = self.clip()
        self.sidecar(video, '.instagram.ok')
        self.assertTrue(confirmado_nas_redes(video, []))
        self.assertTrue(confirmado_nas_redes(str(video), ['instagram']))
        self.assertFalse(confirmado_nas_redes(video, ['tiktok']))
        self.assertFalse(confirmado_nas_redes(video, ['instagram', 'tiktok']))
        self.sidecar(video, '.tiktok.ok')
        self.assertTrue(confirmado_nas_redes(video, ['tiktok']))
        self.assertTrue(confirmado_nas_redes(video, ['instagram', 'tiktok']))

    @unittest.skipUnless(os.name == 'nt', 'Windows short path aliases')
    def test_short_path_alias_recovers_inside_same_canonical_root(self):
        import ctypes
        from ctypes import wintypes
        video, _ = self.clip()
        self.sidecar(video, '.instagram.ok')
        api = ctypes.windll.kernel32.GetShortPathNameW
        api.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
        api.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        length = api(str(self.root), buffer, len(buffer))
        if not length or length >= len(buffer):
            self.skipTest('No short path available for fixture')
        short = Path(buffer.value)
        canonical = self.root.resolve()
        if short == canonical:
            self.skipTest('Volume does not expose a different 8.3 alias')
        failed = short / self.failed.relative_to(self.root)
        ready = short / self.ready.relative_to(self.root)
        self.assertEqual(recuperar_pendentes(canonical, failed, ready,
                         ['tiktok', 'instagram'], self.logs.append), 1)
        target = self.ready / 'nota 08' / video.name
        self.assertEqual(target.read_bytes(), b'video-canal_com_underscores')
        self.assertTrue(target.with_suffix('.instagram.ok').is_file())
        self.assertFalse(video.exists())

    def test_symlink_escapes_are_not_followed(self):
        video, _ = self.clip()
        outside = self.home / 'outside'
        outside.mkdir()
        alien = outside / 'alien_2026-11-20_10-43-51.mp4'
        alien.write_bytes(b'outside')
        try:
            (self.failed / 'escape').symlink_to(outside, target_is_directory=True)
            video.with_name(video.stem + '.instagram.ok').symlink_to(alien)
        except OSError as error:
            self.skipTest('Symlinks unavailable: ' + str(error))
        self.assertEqual(self.recover(), 0)
        self.assertTrue(video.exists())
        self.assertEqual(alien.read_bytes(), b'outside')
        with self.assertRaises(ValueError):
            recuperar_pendentes(self.root, self.failed, self.failed / 'escape', ['tiktok'], self.logs.append)


if __name__ == '__main__':
    unittest.main()
