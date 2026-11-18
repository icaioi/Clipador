"""Canonical channel identities shared by the recorder, live chat and GUI."""
import re
from urllib.parse import urlparse, parse_qs, unquote

_VIDEO = re.compile(r'[A-Za-z0-9_-]{11}\Z')
_CHANNEL = re.compile(r'UC[A-Za-z0-9_-]{22}\Z')
_HANDLE = re.compile(r'@[\w.\-\u00b7]{3,30}\Z', re.UNICODE)
_HOSTS = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be', 'www.youtu.be'}

def normalizar_canal(value):
    value = str(value).strip()
    if not value:
        raise ValueError('Informe o @canal ou o link de uma live do YouTube.')
    if value.startswith('video-') and _VIDEO.fullmatch(value[6:]):
        return value
    if _CHANNEL.fullmatch(value):
        return value
    if _HANDLE.fullmatch(value):
        return value
    if '://' in value or value.lower().startswith(('youtube.com/', 'www.youtube.com/', 'm.youtube.com/', 'youtu.be/')):
        parsed = urlparse(value if '://' in value else 'https://' + value)
        if parsed.scheme not in ('http', 'https') or parsed.hostname not in _HOSTS or parsed.username or parsed.password:
            raise ValueError('Use um link público de youtube.com ou youtu.be.')
        parts = [unquote(p) for p in parsed.path.split('/') if p]
        if parsed.hostname in ('youtu.be', 'www.youtu.be'):
            video = parts[0] if len(parts) == 1 else ''
        elif parts == ['watch']:
            video = parse_qs(parsed.query).get('v', [''])[0]
        elif len(parts) == 2 and parts[0] in ('live', 'shorts'):
            video = parts[1]
        else:
            video = ''
            if len(parts) in (1, 2) and _HANDLE.fullmatch(parts[0]) and (len(parts) == 1 or parts[1] in ('live', 'streams')):
                return parts[0]
            if len(parts) in (2, 3) and parts[0] == 'channel' and _CHANNEL.fullmatch(parts[1]) and (len(parts) == 2 or parts[2] in ('live', 'streams')):
                return parts[1]
        if _VIDEO.fullmatch(video):
            return 'video-' + video
        raise ValueError('Use o @canal, /channel/UC… ou o link /watch?v=… de uma live.')
    if _VIDEO.fullmatch(value):
        return 'video-' + value
    if _HANDLE.fullmatch('@' + value):
        return '@' + value
    raise ValueError('Canal YouTube inválido. Use @canal ou o link de uma live.')

def url_origem(plataforma, canal):
    plataforma = str(plataforma).strip().lower()
    if plataforma == 'youtube':
        canal = normalizar_canal(canal)
        if canal.startswith('video-'):
            return 'https://www.youtube.com/watch?v=' + canal[6:]
        if _CHANNEL.fullmatch(canal):
            return 'https://www.youtube.com/channel/' + canal + '/live'
        return 'https://www.youtube.com/' + canal + '/live'
    if plataforma in ('twitch', 'kick'):
        return ('https://www.twitch.tv/' if plataforma == 'twitch' else 'https://kick.com/') + str(canal)
    raise ValueError('Plataforma de origem não suportada: ' + plataforma)
