from build import replace_functions
from installer_replacements import callback_factory

_CALLBACK=callback_factory(None,None,None,None,None,None).__code__
_TARGET='TelaInicio._instalar_componentes.<locals>.rodar_instalacao'
transform=replace_functions({_TARGET:_CALLBACK})
