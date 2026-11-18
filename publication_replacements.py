def _esperar_publicacao(page, nome, sucesso, auto, botao, timeout_min=10):
    rx_ok = re.compile(sucesso, re.I)
    if auto:
        _vigiar(page, nome, random.uniform(2, 5))
        if not _clicar_publicar(page, botao):
            raise RuntimeError(f'{nome}: botão de publicar não apareceu ou não habilitou')
    else:
        _destacar_botao(page, botao)
        _alarme(f'{nome}: pronto, confira e clique em Publicar')
        print(f'[{nome}] tudo preenchido. Confira e CLIQUE EM PUBLICAR na janela.')
    fim = time.time() + timeout_min * 60
    erro_site = re.compile(r'^(Algo deu errado|Something went wrong|Não foi possível publicar|Couldn.t publish)', re.I)
    while time.time() < fim:
        if page.is_closed():
            raise RuntimeError(f'{nome}: janela de publicação foi fechada antes da confirmação')
        esperar_liberar(page, nome)
        if auto:
            fechar_popups(page)
        texto = page.inner_text('body', timeout=5000)
        if rx_ok.search(texto):
            return True
        mensagens = page.get_by_text(erro_site)
        for i in range(mensagens.count()):
            mensagem = mensagens.nth(i)
            if mensagem.is_visible():
                detalhe = mensagem.inner_text(timeout=2000).strip()[:250]
                raise RuntimeError(f'{nome}: a página recusou a publicação: {detalhe}')
        time.sleep(2)
    raise RuntimeError(f'{nome}: prazo esgotado sem confirmação da publicação; não marcado como postado')
