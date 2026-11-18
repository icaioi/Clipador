"""Offline bytecode edits; no assembler dependency is shipped with Clipador."""
import types
from bytecode import Bytecode, Instr


def _fragment(source, local_names=()):
    body = source + '\n_pipeline_fragment_end = None'
    arguments = list(dict.fromkeys(('self', 'canal', 'p', 'plataformas', 'desativadas', *local_names)))
    signature = ', '.join(name if index == 0 else name + '=None' for index, name in enumerate(arguments))
    module = compile('def injected(' + signature + '):\n' + '\n'.join('    ' + line for line in body.splitlines()), 'clipador_pipeline_patch.py', 'exec')
    function = next(c for c in module.co_consts if isinstance(c, types.CodeType))
    instructions = list(Bytecode.from_code(function))
    assert isinstance(instructions[0], Instr) and instructions[0].name == 'RESUME'
    assert isinstance(instructions[-1], Instr) and instructions[-1].name == 'RETURN_CONST'
    assert isinstance(instructions[-2], Instr) and instructions[-2].name == 'STORE_FAST' and instructions[-2].arg == '_pipeline_fragment_end'
    assert isinstance(instructions[-3], Instr) and instructions[-3].name == 'LOAD_CONST'
    return instructions[1:-3]


def caminhos(code):
    instructions = Bytecode.from_code(code)
    if '_DADOS_DIR' in code.co_names:
        return code
    position = next(i for i, op in enumerate(instructions) if isinstance(op, Instr) and op.name == 'STORE_NAME' and op.arg == 'BASE_DIR')
    # BASE_DIR stays the install/resource root; all defaults use the user's data root.
    for op in instructions[position + 1:]:
        if isinstance(op, Instr) and op.name == 'LOAD_NAME' and op.arg == 'BASE_DIR':
            op.arg = '_DADOS_DIR'
    line = instructions[position].lineno
    instructions[position + 1:position + 1] = [Instr('PUSH_NULL', lineno=line), Instr('LOAD_NAME', 'pasta_dados', lineno=line),
                                              Instr('CALL', 0, lineno=line), Instr('STORE_NAME', '_DADOS_DIR', lineno=line)]
    return instructions.to_code()


def app_counter(code):
    def change(c):
        if c.co_qualname == 'App.__init__' and 'ao_concluir' not in c.co_names:
            instructions = Bytecode.from_code(c)
            position = next(i for i, op in enumerate(instructions) if isinstance(op, Instr) and op.name == 'STORE_ATTR' and op.arg == 'cortador')
            instructions[position + 1:position + 1] = _fragment('self.cortador.ao_concluir = self.incrementar_clipes')
            return instructions.to_code()
        return c.replace(co_consts=tuple(change(v) if isinstance(v, types.CodeType) else v for v in c.co_consts))
    return change(code)


def cortador_counter(code):
    def change(c):
        if c.co_qualname == 'Cortador.finalizar' and 'ao_concluir' not in c.co_consts:
            instructions = Bytecode.from_code(c)
            position = next(i for i, op in enumerate(instructions) if isinstance(op, Instr) and op.name == 'STORE_FAST' and op.arg == 'pronto')
            instructions[position + 1:position + 1] = _fragment("_ao_concluir = getattr(self, 'ao_concluir', None)\nif _ao_concluir is not None:\n    _ao_concluir(canal)")
            return instructions.to_code()
        return c.replace(co_consts=tuple(change(v) if isinstance(v, types.CodeType) else v for v in c.co_consts))
    return change(code)
