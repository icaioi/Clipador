from pathlib import Path
import struct,zlib,marshal,types,dis,sys,os
import ctypes
from ctypes import wintypes
from tempfile import TemporaryDirectory
from xml.dom import minidom

_ASSEMBLY_NS='urn:schemas-microsoft-com:asm.v1'
_APPLICATION_NS='urn:schemas-microsoft-com:asm.v3'
_LONG_PATH_NS='http://schemas.microsoft.com/SMI/2016/WindowsSettings'

def _resource_api():
 """Bind pointer-sized Win32 resource APIs without loading executable code."""
 if os.name!='nt':
  raise OSError('Building frozen executables requires Windows resource APIs')
 api=ctypes.WinDLL('kernel32',use_last_error=True)
 signatures={
  'LoadLibraryExW':([wintypes.LPCWSTR,wintypes.HANDLE,wintypes.DWORD],wintypes.HMODULE),
  'FreeLibrary':([wintypes.HMODULE],wintypes.BOOL),
  'FindResourceExW':([wintypes.HMODULE,ctypes.c_void_p,ctypes.c_void_p,wintypes.WORD],wintypes.HANDLE),
  'SizeofResource':([wintypes.HMODULE,wintypes.HANDLE],wintypes.DWORD),
  'LoadResource':([wintypes.HMODULE,wintypes.HANDLE],wintypes.HANDLE),
  'LockResource':([wintypes.HANDLE],ctypes.c_void_p),
  'BeginUpdateResourceW':([wintypes.LPCWSTR,wintypes.BOOL],wintypes.HANDLE),
  'UpdateResourceW':([wintypes.HANDLE,ctypes.c_void_p,ctypes.c_void_p,wintypes.WORD,ctypes.c_void_p,wintypes.DWORD],wintypes.BOOL),
  'EndUpdateResourceW':([wintypes.HANDLE,wintypes.BOOL],wintypes.BOOL),
 }
 for name,(args,result) in signatures.items():
  function=getattr(api,name);function.argtypes=args;function.restype=result
 return api

def read_application_manifests(path):
 """Read actual RT_MANIFEST / CREATEPROCESS_MANIFEST_RESOURCE_ID resources.

 Language IDs are retained verbatim. Other manifest IDs do not configure the
 executable's process and must not be mistaken for its application manifest.
 """
 api=_resource_api()
 handle=api.LoadLibraryExW(str(Path(path).resolve()),None,0x00000002|0x00000020)
 if not handle:
  raise ctypes.WinError(ctypes.get_last_error())
 try:
  languages=[]
  callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HMODULE,ctypes.c_void_p,ctypes.c_void_p,wintypes.WORD,ctypes.c_ssize_t)
  callback=callback_type(lambda module,kind,name,language,param: languages.append(language) is None)
  enumerate_languages=api.EnumResourceLanguagesW
  enumerate_languages.argtypes=[wintypes.HMODULE,ctypes.c_void_p,ctypes.c_void_p,callback_type,ctypes.c_ssize_t]
  enumerate_languages.restype=wintypes.BOOL
  if not enumerate_languages(handle,24,1,callback,0):
   error=ctypes.get_last_error()
   if error in (1813,1814): # Resource type/name absent: create the application manifest.
    return {}
   raise ctypes.WinError(error)
  manifests={}
  for language in languages:
   resource=api.FindResourceExW(handle,24,1,language)
   if not resource:
    raise ctypes.WinError(ctypes.get_last_error())
   size=api.SizeofResource(handle,resource)
   if not size:
    raise ValueError('Empty executable application manifest')
   loaded=api.LoadResource(handle,resource)
   if not loaded:
    raise ctypes.WinError(ctypes.get_last_error())
   pointer=api.LockResource(loaded)
   if not pointer:
    raise ctypes.WinError(ctypes.get_last_error())
   manifests[language]=ctypes.string_at(pointer,size)
  if not manifests:
   raise ValueError('Application manifest enumeration returned no languages')
  return manifests
 finally:
  if not api.FreeLibrary(handle):
   raise ctypes.WinError(ctypes.get_last_error())

def _manifest_document(data):
 document=minidom.parseString(data)
 root=document.documentElement
 if root.namespaceURI!=_ASSEMBLY_NS or root.localName!='assembly' or root.getAttribute('manifestVersion')!='1.0':
  raise ValueError('Invalid executable application manifest assembly')
 return document

def _children(element,namespace,name):
 return [child for child in element.childNodes if child.nodeType==child.ELEMENT_NODE and child.namespaceURI==namespace and child.localName==name]

def _long_path_settings(document):
 return [setting
         for application in _children(document.documentElement,_APPLICATION_NS,'application')
         for settings in _children(application,_APPLICATION_NS,'windowsSettings')
         for setting in _children(settings,_LONG_PATH_NS,'longPathAware')]

def manifest_long_path_aware(data):
 """Check namespace-qualified settings from PE resource bytes, not source text."""
 document=_manifest_document(data)
 try:
  settings=_long_path_settings(document)
  return bool(settings) and all(
   ''.join(node.data for node in setting.childNodes if node.nodeType in (node.TEXT_NODE,node.CDATA_SECTION_NODE)).strip().lower()=='true'
   for setting in settings)
 finally:
  document.unlink()

def _enable_manifest_long_paths(data):
 document=_manifest_document(data)
 try:
  settings=_long_path_settings(document)
  if not settings:
   applications=_children(document.documentElement,_APPLICATION_NS,'application')
   if applications:
    application=applications[0]
   else:
    application=document.createElementNS(_APPLICATION_NS,'application')
    application.setAttribute('xmlns',_APPLICATION_NS)
    document.documentElement.appendChild(application)
   windows_settings=_children(application,_APPLICATION_NS,'windowsSettings')
   if windows_settings:
    windows=windows_settings[0]
   else:
    windows=document.createElementNS(_APPLICATION_NS,'windowsSettings')
    windows.setAttribute('xmlns',_APPLICATION_NS)
    application.appendChild(windows)
   setting=document.createElementNS(_LONG_PATH_NS,'longPathAware')
   setting.setAttribute('xmlns',_LONG_PATH_NS)
   windows.appendChild(setting);settings=[setting]
  for setting in settings:
   for child in list(setting.childNodes):
    setting.removeChild(child);child.unlink()
   setting.appendChild(document.createTextNode('true'))
  return document.toxml(encoding='utf-8')
 finally:
  document.unlink()

def long_path_aware_stub(prefix):
 """Update only process manifests before appending the PyInstaller overlay.

 BeginUpdateResource may move PE sections or truncate an existing overlay.
 It must therefore operate on the archive-free stub, never the built EXE.
 Existing icons, versions, execution level, DPI settings and resource languages
 are retained; malformed manifests or resource-update failures abort the build.
 """
 if not isinstance(prefix,bytes) or not prefix.startswith(b'MZ'):
  raise ValueError('Expected an archive-free Windows PE stub')
 api=_resource_api()
 with TemporaryDirectory(prefix='clipador-pe-') as temporary:
  path=Path(temporary)/'stub.exe';path.write_bytes(prefix)
  manifests=read_application_manifests(path)
  if not manifests:
   manifests={0:b'<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0"/>'}
  replacements={language:_enable_manifest_long_paths(data) for language,data in manifests.items()}
  update=api.BeginUpdateResourceW(str(path),False)
  if not update:
   raise ctypes.WinError(ctypes.get_last_error())
  try:
   for language,data in replacements.items():
    buffer=ctypes.create_string_buffer(data)
    if not api.UpdateResourceW(update,24,1,language,buffer,len(data)):
     raise ctypes.WinError(ctypes.get_last_error())
  except BaseException:
   if not api.EndUpdateResourceW(update,True):
    raise ctypes.WinError(ctypes.get_last_error())
   raise
  if not api.EndUpdateResourceW(update,False):
   raise ctypes.WinError(ctypes.get_last_error())
  actual=read_application_manifests(path)
  if actual!=replacements or not all(manifest_long_path_aware(data) for data in actual.values()):
   raise ValueError('Executable longPathAware manifest resource verification failed')
  return path.read_bytes()

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
  prefix=long_path_aware_stub(self.prefix)
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
  return prefix+body

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
