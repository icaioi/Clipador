"""Exercise the frozen capture consumer without using the running app's data."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import uuid

from package import Package, ROOT
from integrate import all_transforms
from monitor_transform import transform

HERE = Path(__file__).parent
ENTRY = r"""
import sys
if len(sys.argv) > 1 and sys.argv[1] == '--streamlink':
    from clipador.app import main
    raise SystemExit(main(sys.argv[1:]))
import json, pathlib, threading, time, traceback, tomllib
sys.path.insert(0, SOURCE_DIR)
from clipador.__main__ import App
root = pathlib.Path(sys.argv[1])
config = root / 'canais.toml'
status = root / 'clips' / 'status.json'
errors = []
logs = []
report = {}
app = None
runner = None

def save(channel='', profile=''):
    text = '''[parametros]
segmento_duracao = 2
buffer_segundos = 30
minimo_absoluto = 1000000000
multiplicador = 1000000000.0
cooldown_segundos = 86400
[binarios]
ffmpeg = FFMPEG_VALUE
ffprobe = FFPROBE_VALUE
'''
    text = text.replace('FFMPEG_VALUE', json.dumps(FFMPEG)).replace('FFPROBE_VALUE', json.dumps(FFPROBE))
    if channel:
        text += '''\n[[canais]]
plataforma = "youtube"
canal = "@Gameplayrj"
qualidade = "QUALITY_VALUE"
detector = "ambos"
limiar_db = 1000000000.0
minimo_absoluto = 1000000000
'''.replace('QUALITY_VALUE', channel)
    if profile:
        text += '\n[[perfis]]\nnome = "'+profile+'"\nidioma = "pt"\n'
    pending = config.with_suffix('.tmp')
    pending.write_text(text, encoding='utf-8')
    pending.replace(config)

def wait_for(predicate, seconds=20):
    deadline = time.monotonic()+seconds
    while time.monotonic()<deadline:
        if errors: raise AssertionError(errors)
        if predicate(): return
        time.sleep(.2)
    raise AssertionError('Timed out waiting for monitor consumer state')

def status_data():
    try: return json.loads(status.read_text(encoding='utf-8'))
    except (OSError, ValueError): return None

def run():
    try: app.rodar()
    except BaseException: errors.append(traceback.format_exc())

try:
    save()
    app = App(config, root/'clips', root/'buffer', logs.append, False)
    app._status_json_path = status
    # Both subprocesses execute only this dedicated frozen probe's CLI branch.
    app.cfg.binarios.streamlink = [sys.executable, '--streamlink']
    shared_cfg = app.cfg
    shared_channels = app.cfg.canais
    shared_profiles = app.cfg.perfis
    cutter = app.cortador
    runner = threading.Thread(target=run, daemon=True)
    runner.start()
    wait_for(lambda: status_data() == {})
    assert not app.gravadores
    report['initial_channels'] = 0
    save('720p60')
    key = tomllib.loads(config.read_text(encoding='utf-8'))['canais'][0]['canal'].lower()
    wait_for(lambda: key in app.gravadores)
    recorder = app.gravadores[key]
    detector = app.detectors[key]
    audio = app._monitor_canais.audios[key]
    audio_thread = app._monitor_canais.audio_threads[key]
    readers = list(app._monitor_canais.leitores)
    chat_stop = app._monitor_canais.chat_parada
    assert recorder.parada is not app.parada
    wait_for(lambda: recorder.online and any(p.stat().st_size > 188 for p in recorder.buffer_dir.glob('*.ts')), 150)
    wait_for(lambda: bool((status_data() or {}).get(key, {}).get('online')))
    segments = list(recorder.buffer_dir.glob('*.ts'))
    report['live_ts_bytes'] = sum(p.stat().st_size for p in segments)
    report['online_status'] = status_data()[key]
    save('720p60', 'monitor-isolado')
    wait_for(lambda: bool(app.cfg.perfis))
    assert app.gravadores[key] is recorder and app.detectors[key] is detector
    assert app._monitor_canais.audios[key] is audio
    assert app._monitor_canais.leitores == readers
    assert not chat_stop.is_set()
    assert app.cfg is shared_cfg and app.cfg.canais is shared_channels and app.cfg.perfis is shared_profiles
    assert app.cortador is cutter and cutter.cfg is shared_cfg
    report['unchanged_consumers_preserved'] = True
    config.write_text('[[canais]\n', encoding='utf-8')
    wait_for(lambda: app._monitor_canais.erro_versao is not None)
    assert app.gravadores[key] is recorder and recorder.online
    report['invalid_save_preserves_capture'] = True
    save('1080p60', 'monitor-isolado')
    wait_for(lambda: key in app.gravadores and app.gravadores[key] is not recorder)
    replacement = app.gravadores[key]
    assert recorder.parada.is_set() and not recorder._thread.is_alive()
    assert audio.parada.is_set() and not audio_thread.is_alive()
    assert chat_stop.is_set() and replacement.parada is not app.parada
    assert app.cortador is cutter and not app.parada.is_set()
    report['changed_channel_restarted_only_itself'] = True
    replacement_audio = app._monitor_canais.audios[key]
    replacement_audio_thread = app._monitor_canais.audio_threads[key]
    save()
    wait_for(lambda: not app.gravadores and status_data() == {})
    assert replacement.parada.is_set() and not replacement._thread.is_alive()
    assert replacement_audio.parada.is_set() and not replacement_audio_thread.is_alive()
    assert not app.parada.is_set() and runner.is_alive()
    report['removal_keeps_app_running'] = True
    assert cutter.clipes_feitos == 0 and cutter.fila.empty()
    assert not list((root/'clips').rglob('*.mp4'))
    report['clips_generated'] = 0
    app.parada.set()
    runner.join(timeout=20)
    assert not runner.is_alive() and not errors
    assert all(not worker.is_alive() for worker in cutter.workers)
    assert status_data() == {}
    report['orderly_shutdown'] = True
    report['ok'] = True
except BaseException:
    report['ok'] = False
    report['error'] = traceback.format_exc()
    report['logs'] = logs[-12:]
finally:
    if app is not None: app.parada.set()
    if runner is not None: runner.join(timeout=25)
    (root/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
"""


def main():
    transforms = all_transforms()
    prior = transforms.get('clipador.__main__', lambda code: code)
    transforms['clipador.__main__'] = lambda code: transform(prior(code))
    entry = ('SOURCE_DIR = ' + repr(str(HERE)) + '\nFFMPEG = ' + repr(str(ROOT/'ffmpeg.exe'))
             + '\nFFPROBE = ' + repr(str(ROOT/'ffprobe.exe')) + '\n' + ENTRY)
    probe = ROOT/('ClipadorMonitorCheck-'+uuid.uuid4().hex+'.exe')
    try:
        probe.write_bytes(Package('ClipadorWorker.exe').build(transforms, entry=entry))
        with tempfile.TemporaryDirectory(prefix='clipador-monitor-') as temporary:
            root = Path(temporary)
            env = dict(os.environ, USERPROFILE=str(root/'profile'), HOME=str(root/'profile'))
            result = subprocess.run([str(probe), str(root)], cwd=root, env=env,
                                    capture_output=True, text=True, encoding='utf-8', errors='replace',
                                    creationflags=subprocess.CREATE_NO_WINDOW, timeout=250)
            report = json.loads((root/'report.json').read_text(encoding='utf-8'))
            print(json.dumps(report, ensure_ascii=False, indent=2))
            assert result.returncode == 0 and report['ok'], 'Frozen monitor scenario failed'
    finally:
        probe.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
