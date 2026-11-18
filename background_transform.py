import types
from bytecode import Bytecode, Instr
from pipeline_transforms import _fragment
_NO_WINDOW = 0x08000000


def transform(code):
    def visit(c):
        c = c.replace(co_consts=tuple(visit(v) if isinstance(v,types.CodeType) else v for v in c.co_consts))
        if 'Popen' not in c.co_names:
            return c
        operations = Bytecode.from_code(c)
        # Preserve process groups while suppressing the Windows console.
        if _NO_WINDOW not in c.co_consts:
            for position in range(len(operations)-1,-1,-1):
                op=operations[position]
                if isinstance(op,Instr) and op.name=='LOAD_ATTR' and op.arg[1]=='CREATE_NEW_PROCESS_GROUP':
                    operations[position+1:position+1]=[Instr('LOAD_CONST',_NO_WINDOW),Instr('BINARY_OP',7)]
        calls=[]
        for position,op in enumerate(operations):
            if not (isinstance(op,Instr) and op.name=='LOAD_ATTR' and op.arg[1]=='Popen'):
                continue
            depth=2
            for index in range(position+1,len(operations)):
                candidate=operations[index]
                if not isinstance(candidate,Instr):continue
                if candidate.name=='KW_NAMES' and 'creationflags' in candidate.arg:
                    break
                depth+=candidate.stack_effect()
                if candidate.name=='CALL' and depth==1:
                    kw=operations[index-1]
                    if isinstance(kw,Instr) and kw.name=='KW_NAMES':
                        if 'creationflags' not in kw.arg:calls.append((candidate,kw))
                    else:calls.append((candidate,None))
                    break
            else:raise RuntimeError('Unresolved Popen call in '+c.co_qualname)
        if calls:
            for call,kw in reversed(calls):
                position=operations.index(kw if kw is not None else call)
                values=[Instr('PUSH_NULL'),Instr('LOAD_FAST','creation_flags'),Instr('CALL',0)]
                if kw is None:
                    values.append(Instr('KW_NAMES',('creationflags',)))
                else:kw.arg=kw.arg+('creationflags',)
                operations[position:position]=values
                call.arg+=1
            position=next(i for i,op in enumerate(operations) if isinstance(op,Instr) and op.name=='RESUME')
            operations[position+1:position+1]=_fragment('from clipador.platform_utils import creation_flags')
        return operations.to_code()
    return visit(code)
