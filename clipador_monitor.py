"""Reload channel configuration inside capture; publishers are never restarted here."""
import threading
from clipador.config import carregar_config
from clipador.gravador import GravadorCanal
from clipador.detector import DetectorCanal
from clipador.detector_audio import DetectorAudio
from clipador.chat import iniciar_chats
from clipador.cortador import ClipJob

class MonitorCanais:
    def __init__(self,app,chave):
        self.app=app
        self.chave=chave
        self.canais={}
        self.audios={}
        self.audio_threads={}
        self._callbacks=threading.RLock()
        self.chat_parada=threading.Event()
        self.leitores=[]
        self.versao=None
        self.erro_versao=None

    def _parar_chats(self):
        with self._callbacks:
            self.chat_parada.set()
        for leitor in self.leitores:
            leitor.join(timeout=1)
        self.leitores=[]

    def _parar_canal(self,key):
        audio=self.audios.pop(key,None)
        gravador=self.app.gravadores.get(key)
        with self._callbacks:
            if audio is not None:audio.parada.set()
            if gravador is not None:gravador.parada.set()
        if gravador is not None:
            gravador.stop()
            if gravador._thread is not None:
                gravador._thread.join(timeout=5)
        audio_thread=self.audio_threads.pop(key,None)
        if audio_thread is not None:audio_thread.join(timeout=5)
        with self.app._lock:
            self.app.gravadores.pop(key,None)
            self.app.detectors.pop(key,None)

    def _iniciar_canal(self,canal):
        app=self.app
        key=self.chave(canal.canal)
        parametros=app.p
        # Each recorder owns its stop event; removing it must not stop the app.
        parada=threading.Event()
        gravador=GravadorCanal(app.cfg,canal,app.buffer_dir,parada,log=app.log)
        detector=DetectorCanal(canal=canal.canal,janela_pico_s=parametros.janela_pico_s,
            media_movel_s=parametros.media_movel_s,
            multiplicador=canal.multiplicador if canal.multiplicador is not None else parametros.multiplicador,
            minimo_absoluto=canal.minimo_absoluto if canal.minimo_absoluto is not None else parametros.minimo_absoluto,
            cooldown_segundos=parametros.cooldown_segundos)
        with app._lock:
            app.gravadores[key]=gravador
            app.detectors[key]=detector
        gravador.start()
        modo=canal.detector or ('audio' if canal.plataforma=='kick' else 'chat')
        if modo in ('audio','ambos'):
            def disparar(ts,delta):
                with self._callbacks:
                    if not parada.is_set() and not app.parada.is_set():
                        app.cortador.enfileirar(ClipJob(canal=canal.canal,pico_timestamp=ts,
                            pontuacao=int(delta),mensagens=[],gravador=gravador))
            audio=DetectorAudio(canal.canal,gravador.buffer_dir,app.cfg.binarios.ffmpeg,disparar,
                limiar_db=canal.limiar_db,cooldown_s=parametros.cooldown_segundos,log=app.log)
            self.audios[key]=audio
            audio_thread=threading.Thread(target=audio._loop,daemon=True,name='audio-'+canal.canal)
            self.audio_threads[key]=audio_thread
            audio_thread.start()

    def _aplicar(self,canais,perfis):
        novos={self.chave(canal.canal):canal for canal in canais}
        mudou=novos!=self.canais
        if mudou:self._parar_chats()
        removidos=self.canais.keys()-novos.keys()
        alterados={key for key in self.canais.keys() & novos.keys() if self.canais[key]!=novos[key]}
        for key in removidos|alterados:self._parar_canal(key)
        with self.app._lock:
            self.app.cfg.canais[:]=canais
            self.app.cfg.perfis[:]=perfis
            for key in removidos:self.app.stats.pop(key,None)
        for key in novos.keys()-self.canais.keys() | alterados:
            self._iniciar_canal(novos[key])
        self.canais=novos
        if mudou:
            self.chat_parada=threading.Event()
            parada=self.chat_parada
            def receber(mensagem):
                with self._callbacks:
                    if not parada.is_set() and not self.app.parada.is_set():
                        self.app.registrar_mensagem(*mensagem)
            chats=[canal for canal in canais
                if (canal.detector or ('audio' if canal.plataforma=='kick' else 'chat')) in ('chat','ambos')]
            self.leitores=iniciar_chats(chats,callback=receber,parada=parada,log=self.app.log)
            self.app.log('Monitor atualizado: '+str(len(novos))+' canal(is). Capturas existentes e postagem preservadas.')

    def iniciar(self):
        self._aplicar(list(self.app.cfg.canais),list(self.app.cfg.perfis))
        self.recarregar()

    def recarregar(self):
        try:
            info=self.app.config_path.stat()
            versao=(info.st_mtime_ns,info.st_size)
            if versao==self.versao:return False
            cfg=carregar_config(self.app.config_path)
        except (OSError,ValueError,TypeError,KeyError,AttributeError) as erro:
            assinatura=(type(erro).__name__,str(erro))
            if assinatura!=self.erro_versao:
                self.app.log('Não foi possível atualizar os canais: '+type(erro).__name__+'. Confira canais.toml; monitoramento anterior mantido.')
                self.erro_versao=assinatura
            return False
        self._aplicar(cfg.canais,cfg.perfis)
        self.versao=versao
        self.erro_versao=None
        return True

    def encerrar(self):
        self._parar_chats()
        for key in list(self.canais):self._parar_canal(key)
