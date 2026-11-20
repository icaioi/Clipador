"""Desktop bootstrap: check signed updates, then run exactly one Clipador instance."""
from pathlib import Path
import argparse,ctypes,hashlib,json,os,queue,subprocess,sys,threading,urllib.error
from ctypes import wintypes
from clipador_updater import Updater,UpdateError,UpdateCancelled,InstallationInvalid

class _Mutex:
    def __init__(self,name):
        self.kernel=ctypes.windll.kernel32
        self.kernel.CreateMutexW.restype=wintypes.HANDLE
        self.kernel.CreateMutexW.argtypes=(ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR)
        self.kernel.WaitForSingleObject.argtypes=(wintypes.HANDLE,wintypes.DWORD)
        self.kernel.ReleaseMutex.argtypes=(wintypes.HANDLE,)
        self.kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
        self.handle=self.kernel.CreateMutexW(None,False,name)
        if not self.handle:raise ctypes.WinError()
        self.owned=self.kernel.WaitForSingleObject(self.handle,0) in (0,0x80)
    def close(self):
        if self.handle:
            if self.owned:self.kernel.ReleaseMutex(self.handle)
            self.kernel.CloseHandle(self.handle);self.handle=None

def _running_app():
    class Entry(ctypes.Structure):
        _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),('pid',wintypes.DWORD),
            ('heap',ctypes.c_size_t),('module',wintypes.DWORD),('threads',wintypes.DWORD),
            ('parent',wintypes.DWORD),('priority',wintypes.LONG),('flags',wintypes.DWORD),('name',wintypes.WCHAR*260)]
    kernel=ctypes.windll.kernel32
    kernel.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
    kernel.Process32FirstW.argtypes=(wintypes.HANDLE,ctypes.POINTER(Entry))
    kernel.Process32NextW.argtypes=(wintypes.HANDLE,ctypes.POINTER(Entry))
    kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
    snapshot=kernel.CreateToolhelp32Snapshot(2,0)
    if snapshot==ctypes.c_void_p(-1).value:raise ctypes.WinError()
    entry=Entry();entry.dwSize=ctypes.sizeof(entry)
    session=wintypes.DWORD();kernel.ProcessIdToSessionId(os.getpid(),ctypes.byref(session))
    try:
        available=kernel.Process32FirstW(snapshot,ctypes.byref(entry))
        while available:
            other=wintypes.DWORD()
            if entry.name.casefold()=='clipador.exe' and kernel.ProcessIdToSessionId(entry.pid,ctypes.byref(other)) and other.value==session.value:
                return entry.pid
            available=kernel.Process32NextW(snapshot,ctypes.byref(entry))
    finally:kernel.CloseHandle(snapshot)
    return None

def _activate(pid):
    user=ctypes.windll.user32
    user.GetWindowThreadProcessId.argtypes=(wintypes.HWND,ctypes.POINTER(wintypes.DWORD))
    user.IsWindowVisible.argtypes=(wintypes.HWND,)
    user.ShowWindow.argtypes=(wintypes.HWND,ctypes.c_int)
    user.SetForegroundWindow.argtypes=(wintypes.HWND,)
    @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    def visit(window,unused):
        owner=wintypes.DWORD();user.GetWindowThreadProcessId(window,ctypes.byref(owner))
        if owner.value==pid and user.IsWindowVisible(window):
            user.ShowWindow(window,9);user.SetForegroundWindow(window);return False
        return True
    user.EnumWindows(visit,0)

def _spawn(folder,args,managed=False,origin=None,ready=False):
    executable=folder/('ClipadorLauncher.exe' if managed else 'Clipador.exe')
    command=[str(executable)]
    if managed:
        command+=['--managed','--origin',str(origin)]
        if ready:command.append('--ready')
    if args.teste:command.append('--teste')
    elif args.iniciar:command.append('--iniciar')
    env=os.environ.copy()
    if origin is not None:env['CLIPADOR_ORIGINAL_INSTALL']=str(origin)
    try:
        return subprocess.Popen(command,cwd=folder,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP,env=env)
    except OSError as error:
        if error.filename is None:error.filename=str(executable)
        raise

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--managed',action='store_true')
    parser.add_argument('--origin',type=Path)
    parser.add_argument('--ready',action='store_true')
    parser.add_argument('--teste',action='store_true')
    parser.add_argument('--iniciar',action='store_true')
    args=parser.parse_args(argv)
    folder=Path(sys.executable).parent
    origin=args.origin or folder
    try:
        config=json.loads((folder/'_internal'/'updater-config.json').read_text(encoding='utf-8'))
        identifier=hashlib.sha256(config['repository'].lower().encode()).hexdigest()[:16]
        store=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'Clipador'/'updates'/identifier
        updater=Updater(config,store)
    except (OSError,ValueError,KeyError,UpdateError) as error:
        ctypes.windll.user32.MessageBoxW(None,'Não foi possível carregar o launcher. Extraia o pacote completo novamente.\n'+str(error),'Clipador',0x10)
        return 1
    mutex=_Mutex('Local\\Clipador-'+identifier)
    if not mutex.owned:
        pid=_running_app()
        if pid:_activate(pid)
        else:ctypes.windll.user32.MessageBoxW(None,'O Clipador já está iniciando ou atualizando. Aguarde.','Clipador',0x40)
        mutex.close();return 0
    try:
        if not args.teste:
            pid=_running_app()
            if pid:_activate(pid);return 0
        if args.ready:
            if not args.managed:raise UpdateError('Inicialização de versão sem validação do bootstrap.')
            return _spawn(folder,args,origin=origin).wait()
        return _window(updater,folder,origin,args,mutex)
    except OSError as error:
        code=getattr(error,'winerror',None)
        program=error.filename or str(folder)
        if code==4551:
            title='Execução bloqueada pelo Windows'
            message=('O Controle de Aplicativo do Windows impediu a inicialização do Clipador (erro 4551).\n\n'
                'Programa: '+program+'\n\n'
                'O launcher não pode liberar essa política. Peça ao administrador do PC para revisar o bloqueio '
                'em CodeIntegrity/Operational e autorizar uma distribuição confiável.\n\n'
                'A assinatura das atualizações não substitui a assinatura de editor Authenticode do Windows. '
                'Nenhuma proteção foi desativada.')
        else:
            title='Não foi possível iniciar o Clipador'
            message='O Windows não conseguiu iniciar o programa.\n\nPrograma: '+program+'\n\nDetalhes: '+str(error)
        try:
            updater.store.mkdir(parents=True,exist_ok=True)
            with (updater.store/'updater.log').open('a',encoding='utf-8') as file:
                file.write('launch: WinError '+str(code)+': '+str(error)+'\nPrograma: '+program+'\n')
        except OSError:
            message+='\n\nNão foi possível gravar o log da falha.'
        ctypes.windll.user32.MessageBoxW(None,message,title,0x10)
        return 1
    finally:mutex.close()

def _window(updater,folder,origin,args,mutex):
    import customtkinter as ctk
    from tkinter import messagebox
    ctk.set_appearance_mode('dark')
    window=ctk.CTk();window.title('Clipador · Atualizações');window.geometry('460x210');window.resizable(False,False)
    ctk.CTkLabel(window,text='Clipador',font=ctk.CTkFont(size=26,weight='bold')).pack(pady=(20,8))
    status=ctk.CTkLabel(window,text='Consultando atualizações...',wraplength=410,font=ctk.CTkFont(size=13))
    status.pack(padx=20,pady=8)
    progress=ctk.CTkProgressBar(window,width=410);progress.set(0);progress.pack(pady=14)
    events=queue.Queue();cancel=threading.Event();outcome={}
    updater.notify=lambda text,value:events.put(('progress',text,value))
    updater.cancel=cancel.is_set
    def close():
        cancel.set();status.configure(text='Cancelando com segurança...')
    window.protocol('WM_DELETE_WINDOW',close)
    def work():
        try:
            if not args.managed:
                cached=updater.current()
                if cached is not None and cached!=folder:
                    events.put(('delegate',cached));return
            events.put(('done',updater.prepare(folder)))
        except UpdateCancelled:events.put(('cancelled',))
        except InstallationInvalid as error:events.put(('unusable',str(error)))
        except (urllib.error.URLError,TimeoutError,OSError) as error:events.put(('offline',str(error)))
        except Exception as error:events.put(('error',str(error)))
    def finish(target):
        outcome['target']=target;window.destroy()
    def drain():
        try:
            while True:
                event=events.get_nowait()
                if event[0]=='progress':status.configure(text=event[1]);progress.set(event[2])
                elif event[0] in ('done','delegate'):
                    outcome['ready']=event[0]=='done'
                    finish(None if cancel.is_set() else event[1]);return
                elif event[0]=='cancelled':finish(None);return
                elif event[0] in ('offline','error','unusable'):
                    try:
                        updater.store.mkdir(parents=True,exist_ok=True)
                        with (updater.store/'updater.log').open('a',encoding='utf-8') as file:file.write(event[0]+': '+event[1]+'\n')
                    except OSError:
                        messagebox.showwarning('Log indisponível','Não foi possível gravar o log da atualização. Seus dados foram preservados.',parent=window)
                    if event[0] in ('error','unusable'):
                        messagebox.showwarning('Atualização não aplicada',event[1]+'\n\nNenhum arquivo não verificado será executado.',parent=window)
                    if event[0]=='unusable':finish(None);return
                    if cancel.is_set():finish(None);return
                    status.configure(text='Atualização indisponível. Abrindo a versão instalada...')
                    window.after(1200,lambda:finish(None if cancel.is_set() else folder));return
        except queue.Empty:pass
        window.after(50,drain)
    threading.Thread(target=work,daemon=True).start();window.after(50,drain);window.mainloop()
    target=outcome.get('target')
    if target is None:return 0
    if target!=folder:
        mutex.close()
        _spawn(target,args,managed=True,origin=origin,ready=outcome.get('ready',False))
        return 0
    return _spawn(folder,args,origin=origin).wait()
