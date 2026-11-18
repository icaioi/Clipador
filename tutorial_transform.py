import types

def componentes():
    from clipador_tutorial import componentes_instalados
    return componentes_instalados()

def contas():
    from clipador_tutorial import contas_concluidas
    from clipador.perfis import perfis_da_config
    return contas_concluidas(pasta_dados(),perfis_da_config(carregar_config(ARQUIVO_CANAIS_TOML)))

def inicio():
    from clipador_tutorial import inicio_concluido
    return inicio_concluido(bool(processos_ativos),pasta_dados())

_REPLACEMENTS={702:componentes.__code__,716:contas.__code__,730:inicio.__code__}

def transform(code):
    found=set()
    def visit(c):
        if c.co_qualname=='TelaInicio._criar_widgets.<locals>.<lambda>' and c.co_firstlineno in _REPLACEMENTS:
            replacement=_REPLACEMENTS[c.co_firstlineno]
            assert c.co_argcount==replacement.co_argcount and c.co_freevars==replacement.co_freevars
            found.add(c.co_firstlineno)
            return replacement.replace(co_name=c.co_name,co_qualname=c.co_qualname,co_firstlineno=c.co_firstlineno)
        return c.replace(co_consts=tuple(visit(v) if isinstance(v,types.CodeType) else v for v in c.co_consts))
    result=visit(code)
    assert found==set(_REPLACEMENTS),found
    return result
