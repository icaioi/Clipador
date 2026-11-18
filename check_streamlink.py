from package import Package,ROOT,walk
import subprocess,types

def fix(code):
 if code.co_name=='_rodar_streamlink':
  assert 'streamlink_cli' in code.co_names or 'streamlink_cli.main' in code.co_names
  return code.replace(co_names=tuple('streamlink_cli.main' if n=='streamlink_cli' else n for n in code.co_names))
 return code.replace(co_consts=tuple(fix(x) if isinstance(x,types.CodeType) else x for x in code.co_consts))
