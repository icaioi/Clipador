from pathlib import Path
import types,shutil
from package import ROOT
from check_streamlink import fix as fix_streamlink
HERE=Path(__file__).parent

def functions(path):
    code=compile(path.read_text(encoding='utf-8'),str(path),'exec')
    return {c.co_name:c for c in code.co_consts if isinstance(c,types.CodeType)}

def replace_functions(mapping):
    seen=set()
    def transform(c):
        if c.co_qualname in mapping:
            replacement=mapping[c.co_qualname]
            assert c.co_argcount==replacement.co_argcount,(c.co_qualname,'arguments')
            assert c.co_freevars==replacement.co_freevars,(c.co_qualname,'closures',c.co_freevars,replacement.co_freevars)
            seen.add(c.co_qualname)
            return replacement.replace(co_qualname=c.co_qualname)
        return c.replace(co_consts=tuple(transform(x) if isinstance(x,types.CodeType) else x for x in c.co_consts))
    def run(c):
        seen.clear();result=transform(c);assert seen==set(mapping),(set(mapping)-seen)
        return result
    return run

def capture_transforms():
    recorder=functions(HERE/'recorder_replacements.py')
    return {'clipador.app':fix_streamlink,
            'clipador.gravador':replace_functions({'GravadorCanal._rodar_uma_vez':recorder['_rodar_uma_vez']})}

def deploy_helpers(names):
    for name in names:shutil.copy2(HERE/name,ROOT/'_internal'/name)
