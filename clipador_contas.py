"""Read local session metadata without decrypting or exposing credentials."""
from pathlib import Path
from contextlib import closing
import sqlite3
import time

_AUTH = {'tiktok': ('tiktok.com', ('sessionid', 'sessionid_ss')),
         'instagram': ('instagram.com', ('sessionid',)),
         'youtube': ('google.com', ('SID', '__Secure-1PSID'))}

def estados(pasta):
    paths = (Path(pasta) / 'Default' / 'Network' / 'Cookies',
             Path(pasta) / 'Default' / 'Cookies')
    path = next((p for p in paths if p.exists()), None)
    if path is None:
        return dict.fromkeys(_AUTH, False)
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0.15)) as db:
            rows = db.execute("SELECT host_key, name, expires_utc, is_persistent, "
                              "(length(encrypted_value)>0 OR length(value)>0) FROM cookies "
                              "WHERE name IN ('sessionid','sessionid_ss','SID','__Secure-1PSID')").fetchall()
        now = int((time.time() + 11644473600) * 1000000)
        return {rede: any(host.lstrip('.') == domain and name in names and filled
                         and (not persistent or expiry > now)
                         for host, name, expiry, persistent, filled in rows)
                for rede, (domain, names) in _AUTH.items()}
    except sqlite3.Error:
        return dict.fromkeys(_AUTH, None)

def textos(rede, estado, english=False):
    name = {'tiktok': 'TikTok', 'instagram': 'Instagram', 'youtube': 'YouTube'}[rede]
    if estado is True:
        return (name + (' · Session saved' if english else ' · Sessão salva'),
                ('Open ' if english else 'Abrir ') + name, '#2ecc71')
    if estado is None:
        return (('Close browser to check' if english else 'Feche o navegador para verificar'),
                ('Open ' if english else 'Abrir ') + name, '#e0ad45')
    return (('Not connected' if english else 'Não conectado'),
            ('Sign in to ' if english else 'Entrar ') + name, '#aaaaaa')
