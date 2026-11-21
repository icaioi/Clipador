"""Passive provider restriction parsing and profile-local durable posting blocks."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit


_NETWORKS = {'instagram', 'tiktok', 'youtube'}
_FILENAME = 'restricoes_postagem.json'


def _reason(value):
    if not isinstance(value, str):
        return 'Publicação temporariamente impedida pelo provedor.'
    return ' '.join(''.join(c if c.isprintable() else ' ' for c in value).split())[:500] or 'Publicação impedida pelo provedor.'


class RestricaoPublicacao(RuntimeError):
    def __init__(self, rede, codigo, motivo):
        self.rede = rede
        self.codigo = codigo
        self.motivo = _reason(motivo)
        super().__init__(f'{rede}: publicação bloqueada pelo provedor (código {codigo}): {self.motivo}')


def restricao_da_resposta(response, nome):
    """Inspect only a normal posting response; never initiate network activity."""
    if nome != 'tiktok':
        return None
    try:
        url = urlsplit(response.url)
        host = (url.hostname or '').lower()
        if (url.scheme != 'https' or
                not (host == 'tiktok.com' or host.endswith('.tiktok.com')) or
                response.request.method != 'POST' or
                url.path not in ('/tiktok/web/project/post/v1', '/tiktok/web/project/post/v1/')):
            return None
        body = response.json()
        if not isinstance(body, dict) or type(body.get('status_code')) is not int or body['status_code'] != 21:
            return None
        return RestricaoPublicacao('tiktok', 21, body.get('status_msg'))
    except Exception:
        # Response adapters may fail to decode non-JSON, disposed or malformed responses.
        return None


def _validate_entry(rede, entry):
    if rede not in _NETWORKS or not isinstance(entry, dict):
        raise ValueError('rede ou registro inválido')
    code = entry.get('code')
    if type(code) is not int or (rede == 'tiktok' and code != 21):
        raise ValueError('código de restrição inválido')
    if not isinstance(entry.get('reason'), str) or not entry['reason'].strip():
        raise ValueError('motivo de restrição ausente')
    if not isinstance(entry.get('observed_at'), str):
        raise ValueError('data da restrição ausente')
    observed = datetime.fromisoformat(entry['observed_at'])
    if observed.tzinfo is None:
        raise ValueError('data da restrição sem fuso horário')


def _load(path):
    try:
        with path.open('r', encoding='utf-8') as stream:
            data = json.load(stream)
    except FileNotFoundError:
        return {'schema': 1, 'restricoes': {}}
    except (ValueError, OSError) as exc:
        raise RuntimeError(f'Não foi possível ler {path}. Preserve o arquivo e corrija as restrições antes de retomar postagens: {exc}') from exc
    try:
        if not isinstance(data, dict) or type(data.get('schema')) is not int or data['schema'] != 1 or not isinstance(data.get('restricoes'), dict):
            raise ValueError('esperado schema 1 e mapa restricoes')
        for rede, entry in data['restricoes'].items():
            _validate_entry(rede, entry)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f'Arquivo de restrições inválido: {path}. Preserve o arquivo e corrija-o antes de retomar postagens: {exc}') from exc
    return data


def registrar_restricao(falhas, rede, codigo, motivo, log=print):
    """Merge a block into this profile only; replace atomically without touching media."""
    entry = {'code': codigo, 'reason': _reason(motivo),
             'observed_at': datetime.now(timezone.utc).isoformat()}
    _validate_entry(rede, entry)
    path = Path(falhas) / _FILENAME
    data = _load(path)
    data['restricoes'][rede] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + _FILENAME + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    log(f'{rede}: restrição de postagem registrada para este perfil: {entry["reason"]}. Sem novas tentativas até confirmação de recuperação da conta.')


def restricoes_ativas(falhas, plataformas, log=print):
    data = _load(Path(falhas) / _FILENAME)
    active = set(plataformas) & data['restricoes'].keys()
    for rede in sorted(active):
        entry = data['restricoes'][rede]
        log(f'{rede}: postagem desativada neste perfil por restrição do provedor (código {entry["code"]}): {_reason(entry["reason"])}. Aguardando confirmação de recuperação da conta; mídias pendentes preservadas.')
    return active
