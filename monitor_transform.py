from pathlib import Path
from build import functions, replace_functions


_replacements = functions(Path(__file__).with_name('monitor_replacements.py'))
transform = replace_functions({
    'App.rodar': _replacements['rodar'],
    'App.status_loop': _replacements['status_loop'],
    'App.encerrar': _replacements['encerrar'],
})
