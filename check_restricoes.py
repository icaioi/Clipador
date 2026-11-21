"""Isolated restriction checks: python check_restricoes.py (no network/config)."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import clipador_restricoes
from clipador_restricoes import RestricaoPublicacao, registrar_restricao, restricao_da_resposta, restricoes_ativas


class Response:
    def __init__(self, url='https://www.tiktok.com/tiktok/web/project/post/v1/', method='POST', body=None):
        self.url = url
        self.request = SimpleNamespace(method=method)
        self.body = {'status_code': 21, 'status_msg': 'Account temporarily prevented from posting.'} if body is None else body

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class RestrictionTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='clipador-restricoes-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profile = self.root / 'falhou_postar' / 'perfil a'
        self.logs = []

    def register(self, profile=None, network='tiktok', code=21, reason='Temporarily blocked'):
        registrar_restricao(profile or self.profile, network, code, reason, self.logs.append)

    def active(self, networks=('instagram', 'tiktok'), profile=None):
        return restricoes_ativas(profile or self.profile, networks, self.logs.append)

    def test_exact_posting_api_restriction(self):
        for host in ('tiktok.com', 'www.tiktok.com', 'web.tiktok.com'):
            for suffix in ('', '/'):
                response = Response(url=f'https://{host}/tiktok/web/project/post/v1{suffix}')
                error = restricao_da_resposta(response, 'tiktok')
                self.assertIsInstance(error, RuntimeError)
                self.assertEqual((error.rede, error.codigo, error.motivo), ('tiktok', 21, response.body['status_msg']))
                self.assertIn('21', str(error))

    def test_other_endpoints_hosts_methods_networks_and_bodies_ignored(self):
        cases = [Response(url=url) for url in (
            'http://www.tiktok.com/tiktok/web/project/post/v1/',
            'https://tiktok.com.evil.test/tiktok/web/project/post/v1/',
            'https://nottiktok.com/tiktok/web/project/post/v1/',
            'https://www.tiktok.com/upload/',
            'https://www.tiktok.com/tiktok/web/project/post/v10/',
            'https://[invalid')]
        cases += [Response(method='GET')]
        cases += [Response(body=body) for body in ({'status_code': 0}, {'status_code': 22},
                  {'status_code': '21'}, {}, [], 'bad', ValueError('invalid JSON'))]
        cases += [object()]
        for response in cases:
            with self.subTest(response=response):
                self.assertIsNone(restricao_da_resposta(response, 'tiktok'))
        self.assertIsNone(restricao_da_resposta(Response(), 'instagram'))

    def test_reason_is_bounded_and_ignores_other_fields(self):
        error = restricao_da_resposta(Response(body={'status_code': 21, 'status_msg': '\nblocked\x00' + 'x' * 1000,
                                                    'token': 'never capture', 'cookies': 'never capture'}), 'tiktok')
        self.assertLessEqual(len(error.motivo), 500)
        self.assertNotIn('\n', error.motivo)
        self.assertNotIn('\x00', error.motivo)
        self.assertNotIn('never capture', str(error))
        self.assertTrue(restricao_da_resposta(Response(body={'status_code': 21}), 'tiktok').motivo)

    def test_merge_roundtrip_and_only_configured_returned(self):
        self.assertEqual(self.active(), set())
        self.register(network='youtube', code=9, reason='Provider block')
        self.register()
        self.assertEqual(self.active(), {'tiktok'})
        self.assertEqual(self.active(('youtube', 'tiktok')), {'youtube', 'tiktok'})
        self.assertEqual(self.active(('instagram',)), set())
        data = json.loads((self.profile / 'restricoes_postagem.json').read_text(encoding='utf-8'))
        self.assertEqual(data['schema'], 1)
        self.assertEqual(set(data['restricoes']), {'youtube', 'tiktok'})
        self.assertEqual(data['restricoes']['youtube']['reason'], 'Provider block')
        self.assertIn('observed_at', data['restricoes']['tiktok'])
        self.assertTrue(any('Temporarily blocked' in message for message in self.logs))

    def test_profile_separation_and_media_preservation(self):
        self.profile.mkdir(parents=True)
        preserved = {name: name.encode() for name in ('clip.mp4', 'clip.instagram.ok', 'clip.tiktok.ok', 'clip.json')}
        for name, payload in preserved.items():
            (self.profile / name).write_bytes(payload)
        self.register()
        other = self.root / 'falhou_postar' / 'perfil b'
        self.assertEqual(self.active(profile=other), set())
        self.assertFalse(other.exists())
        self.assertEqual({name: (self.profile / name).read_bytes() for name in preserved}, preserved)

    def test_corrupt_file_preserved_on_read_and_merge(self):
        self.profile.mkdir(parents=True)
        path = self.profile / 'restricoes_postagem.json'
        for content in ('{broken', '{}', '{"schema":1,"restricoes":{"tiktok":{"code":0,"reason":"bad","observed_at":"2026-11-21T00:00:00+00:00"}}}',
                        '{"schema":1,"restricoes":{"unknown":{}}}', '{"schema":1,"restricoes":[]}'):
            path.write_text(content, encoding='utf-8')
            for operation in (self.active, self.register):
                with self.assertRaisesRegex(RuntimeError, 'Preserve'):
                    operation()
                self.assertEqual(path.read_text(encoding='utf-8'), content)

    def test_unknown_network_and_unexpected_tiktok_code_rejected(self):
        for network, code in (('unknown', 21), ('tiktok', 0), ('tiktok', '21'), ('tiktok', True)):
            with self.assertRaises(ValueError):
                self.register(network=network, code=code)
        self.assertFalse(self.profile.exists())

    def test_failed_atomic_replace_keeps_previous_block_and_cleans_temp(self):
        self.register()
        path = self.profile / 'restricoes_postagem.json'
        before = path.read_bytes()
        with patch.object(clipador_restricoes.os, 'replace', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                self.register(network='youtube', code=9)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.profile.iterdir()), [path])

    def test_exception_can_be_persisted_immediately(self):
        error = restricao_da_resposta(Response(), 'tiktok')
        with self.assertRaises(RestricaoPublicacao):
            try:
                raise error
            except RestricaoPublicacao as caught:
                self.register(network=caught.rede, code=caught.codigo, reason=caught.motivo)
                raise
        self.assertEqual(self.active(), {'tiktok'})


if __name__ == '__main__':
    unittest.main()
