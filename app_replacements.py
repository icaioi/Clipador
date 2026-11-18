def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, 'reconfigure'):
            stream.reconfigure(line_buffering=True, write_through=True)
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv[0] == '--iniciar':
        return _abrir_gui()
    if argv[0] == '--clipador':
        return _rodar_clipador(argv)
    if argv[0] == '--postador':
        return _rodar_postador(argv)
    if argv[0] == '--streamlink':
        return _rodar_streamlink(argv)
    if argv[0] == '--teste':
        return _abrir_gui(teste=True)
    return _rodar_clipador(argv)
