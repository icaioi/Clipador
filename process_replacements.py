def creation_flags():
    if IS_WINDOWS:
        return subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    return 0


def kill_proc(proc, timeout=10):
    if proc is None or proc.poll() is not None:
        return
    if IS_WINDOWS:
        result = subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
                                timeout=timeout)
        if result.returncode != 0 and proc.poll() is None:
            raise RuntimeError('Não foi possível encerrar o processo do Clipador: ' +
                               result.stderr.decode('utf-8', errors='replace')[-300:])
        proc.wait(timeout=timeout)
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def shutdown_factory(alvos, self):
    def encerrar():
        from clipador.platform_utils import kill_proc
        for nome, proc in alvos:
            if proc is None or proc.poll() is not None:
                continue
            try:
                kill_proc(proc)
                self._log('SISTEMA', t('encerrado', nome=nome))
            except Exception as erro:
                self._log('ERRO', str(erro))
    return encerrar
