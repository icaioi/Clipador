from pathlib import Path
from tempfile import TemporaryDirectory
import json,sys,types,sqlite3,time
from package import Package,ROOT
sys.path.append(str(ROOT/'_internal'))
from clipador_tutorial import contas_concluidas,inicio_concluido
profiles=types.ModuleType('clipador_test_profiles');sys.modules[profiles.__name__]=profiles
exec(Package().module('clipador.perfis'),profiles.__dict__)
with TemporaryDirectory(prefix='clipador-tutorial-') as folder:
    root=Path(folder)
    main=profiles.Perfil(nome='principal',redes=['tiktok','instagram'])
    extra=profiles.Perfil(nome='Segundo perfil',redes=['tiktok'])
    assert not contas_concluidas(root,[main])
    browser=main.pasta_navegador(root/'perfil_navegador')/'Default'/'Network'/'Cookies'
    browser.parent.mkdir(parents=True)
    with sqlite3.connect(browser) as db:
        db.execute('CREATE TABLE cookies(host_key TEXT,name TEXT,expires_utc INTEGER,is_persistent INTEGER,encrypted_value BLOB,value TEXT)')
        expiry=int((time.time()+11644473600+3600)*1000000)
        db.executemany('INSERT INTO cookies VALUES(?,?,?,?,?,?)',[(host,'sessionid',expiry,1,b'fixture','') for host in ('.tiktok.com','.instagram.com')])
    db.close()
    assert contas_concluidas(root,[main])
    assert not contas_concluidas(root,[main,extra]),'Another profile must not inherit login progress'
    browser.unlink()
    published=main.pasta_postados(root/'clipes');published.mkdir(parents=True)
    (published/'example.tiktok.ok').touch()
    assert not contas_concluidas(root,[main]),'Partial publication must not complete another network'
    (published/'example.instagram.ok').touch()
    assert contas_concluidas(root,[main]),'Completed login remains completed when browser locks cookies'
    assert not contas_concluidas(root,[main,extra])
    empty=root/'fresh'
    assert not inicio_concluido(False,empty)
    assert inicio_concluido(True,empty)
    assert inicio_concluido(False,empty),'First execution must survive stop/restart'
    assert inicio_concluido(False,root),'Previously confirmed publication proves first execution'
print(json.dumps({'modern_cookie_path':True,'all_enabled_networks_required':True,'profiles_isolated':True,'previous_publication_recognized':True,'execution_progress_persistent':True}))
