import types
from bytecode import Bytecode,Instr
from pipeline_transforms import _fragment

def transform(code):
 def visit(c):
  if c.co_qualname=='ClipadorApp.run' and '--iniciar' not in c.co_consts:
   instructions=Bytecode.from_code(c)
   position=next(i for i,op in enumerate(instructions) if isinstance(op,Instr) and op.name=='LOAD_ATTR' and op.arg==(True,'mainloop'))
   instructions[position-2:position-2]=_fragment("if '--iniciar' in sys.argv and not self.teste:\n    self.janela.after(1000, self._iniciar_tudo)")
   return instructions.to_code()
  return c.replace(co_consts=tuple(visit(v) if isinstance(v,types.CodeType) else v for v in c.co_consts))
 return visit(code)
