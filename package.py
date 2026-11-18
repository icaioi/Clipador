from pathlib import Path
import struct,zlib,marshal,types,dis,sys,os
ROOT=Path(os.environ.get('CLIPADOR_RUNTIME_ROOT') or Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'Programs'/'Clipador')
MAGIC=b'MEI\014\013\012\013\016'
def archive(binary):
 i=binary.rfind(MAGIC);_,size,off,n,version,lib=struct.unpack('!8sIIII64s',binary[i:i+88]);assert version==312 and i+88==len(binary)
 start=i+88-size;table=binary[start+off:start+off+n];pos=0;entries=[]
 while pos<len(table):
  k,o,c,raw,flag,kind=struct.unpack('!IIIIBc',table[pos:pos+18]);name=table[pos+18:pos+k];pos+=k;data=binary[start+o:start+o+c]
  entries.append((name,flag,kind,raw,data))
 return binary[:start],entries,version,lib
class Package:
 def __init__(self,name='Clipador.exe'):
  self.binary=(ROOT/name).read_bytes();self.prefix,self.entries,self.version,self.lib=archive(self.binary)
  self.pyz=next(d for n,f,k,r,d in self.entries if n.rstrip(b'\0')==b'PYZ.pyz')
  self.toc=dict(marshal.loads(self.pyz[struct.unpack('!I',self.pyz[8:12])[0]:]))
 def module(self,name):
  _,o,n=self.toc[name];return marshal.loads(zlib.decompress(self.pyz[o:o+n]))
 def build(self,transforms=None,entry=None):
  transforms=transforms or {};body=bytearray();table=bytearray()
  for name,flag,kind,raw,data in self.entries:
   key=name.rstrip(b'\0')
   if key==b'PYZ.pyz':
    assert not flag
    pyz=bytearray(self.pyz[:12]);toc=[]
    for module,(typ,o,n) in self.toc.items():
     chunk=self.pyz[o:o+n]
     if module in transforms:chunk=zlib.compress(marshal.dumps(transforms[module](self.module(module))),9)
     toc.append((module,(typ,len(pyz),len(chunk))));pyz.extend(chunk)
    off=len(pyz);pyz.extend(marshal.dumps(toc));pyz[8:12]=struct.pack('!I',off);data=bytes(pyz);raw=len(data)
   elif key==b'clipador_exe' and entry is not None:
    chunk=marshal.dumps(compile(entry,'clipador_probe.py','exec'));raw=len(chunk);data=zlib.compress(chunk) if flag else chunk
   off=len(body);body.extend(data);table.extend(struct.pack('!IIIIBc',18+len(name),off,len(data),raw,flag,kind)+name)
  off=len(body);body.extend(table);body.extend(struct.pack('!8sIIII64s',MAGIC,len(body)+88,off,len(table),self.version,self.lib))
  return self.prefix+body

def walk(code):
 yield code
 for x in code.co_consts:
  if isinstance(x,types.CodeType):yield from walk(x)
if __name__=='__main__':
 package=Package()
 for name in sys.argv[1:]:
  print('MODULE',name)
  for code in walk(package.module(name)):
   print('FUNCTION',code.co_qualname,'ARGS',code.co_varnames[:code.co_argcount+code.co_kwonlyargcount],'GLOBALS',code.co_names,'STRINGS',[x for x in code.co_consts if isinstance(x,str)])
