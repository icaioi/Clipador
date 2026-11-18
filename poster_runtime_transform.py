import types
from bytecode import Bytecode,Instr
from pipeline_transforms import _fragment

def transform(code):
    def visit(c):
        if c.co_qualname=='rodar':
            instructions=Bytecode.from_code(c)
            if '_poster_browser' not in c.co_varnames:
                position=next(i for i,op in enumerate(instructions) if isinstance(op,Instr) and op.name=='LOAD_GLOBAL' and op.arg==(True,'postar_tiktok'))
                instructions[position:position]=_fragment("_poster_browser = ctx.browser\nif (_poster_browser is not None and not _poster_browser.is_connected()) or (_poster_browser is None and not ctx.pages):\n    _registrar('Navegador de postagem encerrado; reabrindo a sessão salva.')\n    ctx = _abrir(p)")
            if 'Postador interrompido: todas as redes estão desativadas.' not in c.co_consts:
                position=next(i for i,op in enumerate(instructions) if isinstance(op,Instr) and op.name=='LOAD_GLOBAL' and op.arg==(True,'_fila_por_nota'))
                instructions[position:position]=_fragment("if not plataformas or len(desativadas) >= len(plataformas):\n    _registrar('Postador interrompido: todas as redes estão desativadas.')\n    _alarme('Todas as redes falharam. A fila foi preservada; confira o erro em postados.log.')\n    raise RuntimeError('Todas as redes estão desativadas; nenhum vídeo novo será consumido.')")
                position=next(i for i,op in enumerate(instructions) if isinstance(op,Instr) and op.name=='STORE_FAST' and op.arg=='ok_todos')
                assert isinstance(instructions[position-1],Instr) and instructions[position-1].name=='LOAD_CONST' and instructions[position-1].arg is True
                instructions[position-1:position]=[Instr('LOAD_FAST','desativadas'),Instr('UNARY_NOT')]
            for op in instructions:
                if isinstance(op,Instr) and op.name=='LOAD_GLOBAL' and op.arg==(True,'print'):
                    op.arg=(True,'_registrar')
            return instructions.to_code()
        return c.replace(co_consts=tuple(visit(v) if isinstance(v,types.CodeType) else v for v in c.co_consts))
    return visit(code)
