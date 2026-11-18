def rodar(self):
    from clipador_monitor import MonitorCanais
    self._monitor_canais = MonitorCanais(self, _chave)
    try:
        self.cortador.iniciar()
        self._monitor_canais.iniciar()
        self.log('Clipador rodando. Canais salvos são atualizados automaticamente. Ctrl+C para encerrar.')
        self.status_loop()
    except KeyboardInterrupt:
        pass
    finally:
        self.encerrar()


def status_loop(self):
    proximo_status = 0.0
    proximo_json = 0.0
    while not self.parada.wait(1.0):
        mudou = self._monitor_canais.recarregar()
        agora = time.time()
        if agora >= proximo_status:
            proximo_status = agora + JANELA_STATUS_S
            self._imprimir_status(agora)
        if mudou or agora >= proximo_json:
            proximo_json = agora + STATUS_JSON_INTERVALO
            self._escrever_status_json(agora)


def encerrar(self):
    self.log('Encerrando clipador...')
    self.parada.set()
    monitor = getattr(self, '_monitor_canais', None)
    try:
        if monitor is not None:
            monitor.encerrar()
    finally:
        self.cortador.parar()
        self._escrever_status_json(time.time())
    self.log('Encerrado.')
