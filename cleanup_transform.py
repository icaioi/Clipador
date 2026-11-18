import types
from bytecode import Bytecode,Instr
from pipeline_transforms import _fragment

def transform(code):
    def visit(c):
        if c.co_qualname=='rodar' and 'clipador_cleanup' not in c.co_names:
            operations=Bytecode.from_code(c)
            stores=[i for i,op in enumerate(operations) if isinstance(op,Instr) and op.name=='STORE_FAST' and op.arg=='ultimo_post']
            position=stores[-1]-3
            assert operations[position].name=='LOAD_GLOBAL' and operations[position].arg==(True,'time')
            operations[position:position]=_fragment("if ok_todos:\n    from clipador_cleanup import limpar_publicado\n    limpar_publicado(postados / video.name, _clipes_dir(), plataformas, _registrar)",local_names=('ok_todos','postados','video'))
            return operations.to_code()
        return c.replace(co_consts=tuple(visit(v) if isinstance(v,types.CodeType) else v for v in c.co_consts))
    return visit(code)
