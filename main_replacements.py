def teste_chat(plataforma, canal, cfg, log=print):
    from clipador.config import CanalConfig
    from clipador_youtube import normalizar_canal
    plataforma = plataforma.lower()
    if plataforma not in ('twitch', 'kick', 'youtube'):
        log('Plataforma desconhecida: ' + plataforma)
        return
    if plataforma == 'youtube':
        canal = normalizar_canal(canal)
    p = cfg.parametros
    parada = threading.Event()
    det = DetectorCanal(canal=canal, janela_pico_s=p.janela_pico_s, media_movel_s=p.media_movel_s,
                        multiplicador=p.multiplicador, minimo_absoluto=p.minimo_absoluto,
                        cooldown_segundos=p.cooldown_segundos)
    def cb(msg):
        _canal, usuario, texto, ts = msg
        det.recebem(texto, ts)
        pontos = DetectorCanal.pontuar(texto)
        log(f'[{time.strftime("%H:%M:%S",time.localtime(ts))}] {usuario}: {texto}  (pontos={pontos})')
    readers = iniciar_chats([CanalConfig(plataforma=plataforma, canal=canal)], cb, parada, log)
    log(f'Teste de chat: {plataforma} #{canal} (Ctrl+C para sair)')
    proximo = time.time() + 5
    try:
        while not parada.wait(.5):
            agora = time.time()
            if agora >= proximo:
                proximo = agora + 5
                pico, media, limite = det.taxa_atual(agora)
                dispararia = det.dispararia_agora(agora)
                log(f'taxa pico {pico} | media {media:.2f}/s | limite {limite:.2f} | dispararia: {"sim" if dispararia else "nao"}')
    except KeyboardInterrupt:
        pass
    finally:
        parada.set()
        for reader in readers:
            reader.join(timeout=1)
