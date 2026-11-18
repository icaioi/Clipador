def main(argv=None):
    global AUTO, PRIVADO, NOTA_MINIMA
    redes_validas = ('tiktok', 'instagram', 'youtube')
    def ler_redes(value):
        redes = [parte.strip().lower() for parte in value.split(',')]
        if not redes or any(rede not in redes_validas for rede in redes):
            raise argparse.ArgumentTypeError('Use tiktok, instagram ou youtube, separados por vírgulas.')
        return list(dict.fromkeys(redes))
    ap = argparse.ArgumentParser(prog='clipador.postador')
    ap.add_argument('--login', action='store_true', help='abre o navegador para você logar (1ª vez)')
    ap.add_argument('--refazer-login', choices=redes_validas, help='apaga a sessão desse site e abre o login de novo')
    ap.add_argument('--perfil', default='principal', help='perfil de postagem (padrão: principal)')
    ap.add_argument('--privado', action='store_true', help="TikTok: posta como 'Somente eu' (teste)")
    ap.add_argument('--auto', action='store_true', help='clica em Publicar sozinho')
    ap.add_argument('--so', type=ler_redes, metavar='REDES', help='redes separadas por vírgulas, ex.: tiktok,instagram')
    ap.add_argument('--intervalo-min', type=float, default=6.0)
    ap.add_argument('--intervalo-max', type=float, default=8.0)
    ap.add_argument('--nota-minima', type=int, default=6)
    a = ap.parse_args(argv)
    _definir_perfil(a.perfil)
    if a.login or a.refazer_login:
        login(a.refazer_login, perfil=a.perfil)
        return 0
    AUTO = a.auto
    PRIVADO = a.privado
    NOTA_MINIMA = a.nota_minima
    plats = a.so if a.so else list(_redes_do_perfil())
    rodar(a.auto, plats, (a.intervalo_min, a.intervalo_max), perfil=a.perfil, redes_perfil=_redes_do_perfil())
    return 0
