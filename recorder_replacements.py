def _rodar_uma_vez(self):
    from clipador_youtube import url_origem
    import tempfile
    self.inicio_buffer = time.time()
    self.online = False
    self.ultimo_erro = ''
    self._binario_ausente = False
    stamp = str(int(self.inicio_buffer))
    saida = str(self.buffer_dir / (stamp + '_%06d.ts'))
    canal = self.canal_cfg
    sl_args = [*self.cfg.binarios.streamlink, url_origem(canal.plataforma, canal.canal),
               canal.qualidade, '--stdout']
    if canal.plataforma.lower() == 'twitch':
        sl_args.append('--twitch-disable-ads')
    ff_args = [self.cfg.binarios.ffmpeg, '-hide_banner', '-loglevel', 'error',
               '-i', 'pipe:0', '-c', 'copy', '-f', 'segment', '-segment_time',
               str(self.segmento_duracao), '-reset_timestamps', '1', saida]
    self.log(f'[gravador:{canal.canal}] iniciando {canal.plataforma}: streamlink+ffmpeg')
    with tempfile.TemporaryFile() as sl_log, tempfile.TemporaryFile() as ff_log:
        try:
            try:
                self.streamlink_proc = subprocess.Popen(sl_args, stdout=subprocess.PIPE, stderr=sl_log,
                                                        creationflags=creation_flags())
            except FileNotFoundError:
                self.ultimo_erro = 'streamlink nao encontrado'
                self._binario_ausente = True
                self._log_binario_ausente(f'[gravador:{canal.canal}] {self.ultimo_erro}; tentando de novo em 60 s')
                return
            try:
                self.proc = subprocess.Popen(ff_args, stdin=self.streamlink_proc.stdout,
                                             stdout=subprocess.DEVNULL, stderr=ff_log,
                                             creationflags=creation_flags())
            except FileNotFoundError:
                self.ultimo_erro = 'ffmpeg nao encontrado'
                self._binario_ausente = True
                self._log_binario_ausente(f'[gravador:{canal.canal}] {self.ultimo_erro}; tentando de novo em 60 s')
                return
            finally:
                if self.streamlink_proc.stdout is not None:
                    self.streamlink_proc.stdout.close()
                    self.streamlink_proc.stdout = None
            while not self.parada.is_set():
                if self.streamlink_proc.poll() is not None or self.proc.poll() is not None:
                    break
                if not self.online:
                    for segment in self.buffer_dir.glob(stamp + '_*.ts'):
                        try:
                            if segment.stat().st_size > 188:
                                self.online = True
                                self.log(f'[gravador:{canal.canal}] recebendo vídeo')
                                break
                        except FileNotFoundError:
                            pass
                self.parada.wait(1)
        finally:
            self.online = False
            sl_code = self.streamlink_proc.poll() if self.streamlink_proc else None
            ff_code = self.proc.poll() if self.proc else None
            self._encerrar()
            self._limpar_buffer()
            if not self.parada.is_set() and not self._binario_ausente:
                messages = []
                for output in (sl_log, ff_log):
                    output.seek(0, 2)
                    size = output.tell()
                    output.seek(max(0, size - 1500))
                    text = output.read().decode('utf-8', errors='replace').strip()
                    if text:
                        messages.append(text)
                self.ultimo_erro = '\n'.join(messages)[-1500:] or f'Captura encerrada (streamlink={sl_code}, ffmpeg={ff_code})'
                self.log(f'[gravador:{canal.canal}] {self.ultimo_erro}')
