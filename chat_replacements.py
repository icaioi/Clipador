"""Replacement code objects for the bundled clipador.chat module."""


def iniciar_chats(canais, callback, parada, log=print):
    """Start one daemon chat reader per supported channel, preserving identity."""
    import threading
    from clipador.chat import iterar_twitch, iterar_kick
    from youtube_chat import iterar_youtube

    threads = []
    for c in canais:
        plataforma = c.plataforma.lower()
        canal = c.canal
        if plataforma == "twitch":
            target = iterar_twitch
            args = (canal, callback, parada, log)
        elif plataforma == "kick":
            target = iterar_kick
            args = (canal, callback, parada, c.chatroom_id, log)
        elif plataforma == "youtube":
            target = iterar_youtube
            args = (canal, callback, parada, log)
        else:
            continue
        t = threading.Thread(target=target, args=args, daemon=True)
        t.start()
        threads.append(t)
    return threads
