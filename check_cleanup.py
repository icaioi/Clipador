from pathlib import Path
from tempfile import TemporaryDirectory
import json
from clipador_cleanup import limpar_publicado

with TemporaryDirectory(prefix='clipador-cleanup-') as directory:
    home=Path(directory);root=home/'clipes';legacy=home/'legacy';logs=[]
    def fixture(name):
        video=root/'postados'/('fixture_'+name+'_2026-11-18_10-43-51.mp4')
        video.parent.mkdir(parents=True,exist_ok=True);video.write_bytes(b'confirmed-video')
        source=root/'2026-11-18'/('fixture_'+name+'_10-43-51')
        source.parent.mkdir(parents=True,exist_ok=True)
        media=[source.with_name(source.name+suffix) for suffix in ('.bruto.mp4','.cortado.mp4','.vertical.mp4')]
        for path in media:path.write_bytes(b'generated-video')
        preserved=[video.with_suffix('.txt'),source.with_suffix('.json')]
        for path in preserved:path.write_text('record',encoding='utf-8')
        for network in ('tiktok','instagram'):
            video.with_name(video.stem+'.'+network+'.ok').touch()
        return video,media,preserved
    video,media,preserved=fixture('partial')
    video.with_name(video.stem+'.instagram.ok').unlink()
    assert limpar_publicado(video,root,['tiktok','instagram'],logs.append,legacy)==0
    assert all(path.exists() for path in [video,*media,*preserved])
    video,media,preserved=fixture('complete')
    old_source=legacy/'2026-11-18'/'fixture_complete_10-43-51.bruto.mp4'
    old_source.parent.mkdir(parents=True);old_source.write_bytes(b'generated-video')
    retired=legacy/'PRONTOS PARA POSTAR'/video.name
    retired.parent.mkdir();retired.write_bytes(video.read_bytes())
    unrelated=retired.with_name('unrelated.mp4');unrelated.write_bytes(b'keep')
    assert limpar_publicado(video,root,['tiktok','instagram'],logs.append,legacy)==6
    assert not any(path.exists() for path in [video,*media,old_source,retired])
    assert all(path.exists() for path in [*preserved,unrelated])
    proof=json.loads(video.with_suffix('.publicacao.json').read_text(encoding='utf-8'))
    assert len(proof['arquivos_removidos'])==6 and not proof['falhas_limpeza']
    assert all(video.with_name(video.stem+'.'+network+'.ok').exists() for network in ('tiktok','instagram'))
    video,media,preserved=fixture('pending')
    pending=root/'PRONTOS PARA POSTAR'/'another-profile'/video.name
    pending.parent.mkdir(parents=True);pending.write_bytes(b'still-pending')
    assert limpar_publicado(video,root,['tiktok','instagram'],logs.append,legacy)==1
    assert all(path.exists() for path in [*media,*preserved,pending]) and not video.exists()
    outside=home/'outside.mp4';outside.write_bytes(b'keep')
    try:limpar_publicado(outside,root,['tiktok'],logs.append,legacy)
    except ValueError:pass
    else:raise AssertionError('Unsafe path accepted')
    assert outside.exists()
    print(json.dumps({'partial_publication_preserved':True,'confirmed_media_removed':True,
        'other_profile_pending_preserved':True,'history_preserved':True,'outside_files_protected':True}))

from package import Package
from integrate import all_transforms
transforms=all_transforms()
for name,transform in transforms.items():
    transform(Package().module(name))
print('Package integration compiled successfully')
