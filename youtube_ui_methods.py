"""Source-only replacements for code objects in clipador.gui.__main__."""


class DialogCanal:
    def _criar_widgets(self):
        english = idioma_ativo().lower().startswith('en')

        def add_label(texto, r):
            ctk.CTkLabel(self, text=texto, anchor='w').grid(
                row=r, column=0, padx=20, pady=(15, 0), sticky='w')

        add_label(t('dlg_canal_plataforma'), 0)
        self.combo_plataforma = ctk.CTkComboBox(
            self, values=['Twitch', 'Kick', 'YouTube'], state='readonly')
        self.combo_plataforma.grid(row=0, column=1, padx=20, pady=(15, 0), sticky='ew')
        self.combo_plataforma.set('Twitch')
        add_label(t('dlg_canal_nome'), 1)
        self.entry_canal = ctk.CTkEntry(self)
        self.entry_canal.grid(row=1, column=1, padx=20, pady=(15, 0), sticky='ew')

        def selecionar_plataforma(valor):
            if valor == 'YouTube':
                texto = ('@handle, channel or live URL' if english
                         else '@canal, URL do canal ou da live')
            elif valor == 'Kick':
                texto = 'ex: coringa / https://kick.com/coringa'
            else:
                texto = 'ex: coringa / https://twitch.tv/coringa'
            self.entry_canal.configure(placeholder_text=texto)

        self.combo_plataforma.configure(command=selecionar_plataforma)
        selecionar_plataforma('Twitch')
        add_label(t('dlg_canal_perfil'), 2)
        self.entry_perfil = ctk.CTkEntry(
            self, placeholder_text=t('dlg_canal_perfil_placeholder'))
        self.entry_perfil.grid(row=2, column=1, padx=20, pady=(15, 0), sticky='ew')
        add_label(t('dlg_canal_sens'), 3)
        self.combo_sens = ctk.CTkComboBox(
            self, values=[t('sens_baixa'), t('sens_media'), t('sens_alta')],
            state='readonly')
        self.combo_sens.grid(row=3, column=1, padx=20, pady=(15, 0), sticky='ew')
        self.combo_sens.set(t('sens_media'))
        add_label(t('dlg_canal_jogo'), 4)
        self.entry_jogo = ctk.CTkEntry(self, placeholder_text='GTA 6')
        self.entry_jogo.grid(row=4, column=1, padx=20, pady=(15, 0), sticky='ew')
        add_label(t('dlg_canal_hashtags'), 5)
        self.entry_hashtags_obg = ctk.CTkEntry(self, placeholder_text='#ngcash #campanha')
        self.entry_hashtags_obg.grid(row=5, column=1, padx=20, pady=(15, 0), sticky='ew')
        add_label(t('dlg_canal_mencoes'), 6)
        self.entry_mencoes = ctk.CTkEntry(self, placeholder_text='@ng.cash @marca')
        self.entry_mencoes.grid(row=6, column=1, padx=20, pady=(15, 0), sticky='ew')
        add_label(t('dlg_canal_texto'), 7)
        self.entry_texto_video = ctk.CTkEntry(self, placeholder_text='twitch.tv/facada')
        self.entry_texto_video.grid(row=7, column=1, padx=20, pady=(15, 0), sticky='ew')
        add_label(t('dlg_canal_marca'), 8)
        frame_arquivo = ctk.CTkFrame(self, fg_color='transparent')
        frame_arquivo.grid(row=8, column=1, padx=20, pady=(15, 0), sticky='ew')
        frame_arquivo.grid_columnconfigure(0, weight=1)
        self.entry_marca = ctk.CTkEntry(
            frame_arquivo, placeholder_text=('Select .png or .mov/.mp4' if english
                                             else 'Selecione .png ou .mov/.mp4'))
        self.entry_marca.grid(row=0, column=0, sticky='ew', padx=(0, 5))
        ctk.CTkButton(frame_arquivo, text='', image=icone('pasta', 18), width=40,
                      command=self._selecionar_arquivo).grid(row=0, column=1)
        frame_botoes = ctk.CTkFrame(self, fg_color='transparent')
        frame_botoes.grid(row=9, column=0, columnspan=2, pady=20)
        ctk.CTkButton(frame_botoes, text=t('salvar'), width=120,
                      command=self._salvar).pack(side='left', padx=10)
        ctk.CTkButton(frame_botoes, text=t('cancelar'), width=100,
                      command=self.destroy).pack(side='left', padx=10)

    def _preencher_dados(self):
        c = self.canal
        plataforma = {'youtube': 'YouTube', 'twitch': 'Twitch', 'kick': 'Kick'}.get(
            c.plataforma, c.plataforma.capitalize())
        self.combo_plataforma.set(plataforma)
        if c.plataforma == 'youtube':
            self.entry_canal.configure(placeholder_text='@canal / https://youtube.com/@canal/live')
        self.entry_canal.insert(0, c.canal)
        if c.perfis:
            self.entry_perfil.insert(0, ', '.join(c.perfis))
        elif c.perfil:
            self.entry_perfil.insert(0, c.perfil)
        if c.plataforma == 'kick':
            sens = t('sens_alta') if c.limiar_db <= 5 else t('sens_media') if c.limiar_db <= 7 else t('sens_baixa')
        else:
            minimo = (c.minimo_absoluto if c.minimo_absoluto is not None else
                      carregar_config(ARQUIVO_CANAIS_TOML).parametros.minimo_absoluto)
            sens = t('sens_alta') if minimo <= 5 else t('sens_media') if minimo <= 10 else t('sens_baixa')
        self.combo_sens.set(sens)
        self.entry_jogo.insert(0, c.jogo or 'GTA 6')
        self.entry_hashtags_obg.insert(0, c.hashtags_obrigatorias or '')
        self.entry_mencoes.insert(0, c.mencoes or '')
        self.entry_texto_video.insert(0, c.texto_no_video or '')
        self.entry_marca.insert(0, c.marca_campanha or '')

    def _salvar(self):
        import tomllib
        from clipador_youtube import normalizar_canal

        plataforma = self.combo_plataforma.get().lower()
        canal_nome = self.entry_canal.get().strip()
        english = idioma_ativo().lower().startswith('en')
        if plataforma == 'youtube':
            try:
                canal_nome = normalizar_canal(canal_nome)
            except ValueError:
                self.tela_canais.app._mostrar_aviso(
                    ('Enter a YouTube @handle, channel ID, channel URL or live/video URL.'
                     if english else
                     'Informe um @canal, ID de canal ou URL do canal, vídeo ou live do YouTube.'))
                self.entry_canal.focus_set()
                return
        else:
            if 'twitch.tv/' in canal_nome:
                canal_nome = canal_nome.split('twitch.tv/')[-1].split('/')[0].split('?')[0]
            elif 'kick.com/' in canal_nome:
                canal_nome = canal_nome.split('kick.com/')[-1].split('/')[0].split('?')[0]
        if not canal_nome:
            self.tela_canais.app._mostrar_aviso(t('col_canal'))
            self.entry_canal.focus_set()
            return

        def identidade(plataforma, nome):
            if plataforma.lower() == 'youtube':
                return normalizar_canal(nome)
            return nome.lower()

        sens = self.combo_sens.get()
        with ARQUIVO_CANAIS_TOML.open('rb') as f:
            dados = tomllib.load(f)
        canais = dados.setdefault('canais', [])
        indice = None
        anterior = {}
        if self.editando:
            for i, c in enumerate(canais):
                if (c.get('plataforma', '').lower() == self.canal.plataforma.lower()
                        and identidade(self.canal.plataforma, c.get('canal', ''))
                        == identidade(self.canal.plataforma, self.canal.canal)):
                    indice = i
                    anterior = c
                    break
            if indice is None:
                self.tela_canais.app._mostrar_aviso(
                    ('This channel changed. Close this dialog and open it again.' if english else
                     'Este canal foi alterado. Feche esta janela e abra o canal novamente.'))
                return
        # Keep fields not represented by this dialog, including quality and capture metadata.
        novo_canal = dict(anterior)
        novo_canal.setdefault('qualidade', '720p60,720p,best')
        novo_canal.setdefault('chatroom_id', '')
        novo_canal.setdefault('limiar_db', 7.0)
        novo_canal.update(
            plataforma=plataforma, canal=canal_nome,
            jogo=self.entry_jogo.get().strip() or 'GTA 6',
            hashtags_obrigatorias=self.entry_hashtags_obg.get().strip(),
            mencoes=self.entry_mencoes.get().strip(),
            texto_no_video=self.entry_texto_video.get().strip(),
            marca_campanha=self.entry_marca.get().strip())
        if anterior and (plataforma != self.canal.plataforma or
                         identidade(plataforma, canal_nome) !=
                         identidade(self.canal.plataforma, self.canal.canal)):
            novo_canal['chatroom_id'] = ''
        if plataforma == 'kick':
            novo_canal['limiar_db'] = 5 if sens == t('sens_alta') else 7 if sens == t('sens_media') else 9
            novo_canal.pop('minimo_absoluto', None)
        else:
            novo_canal['minimo_absoluto'] = 5 if sens == t('sens_alta') else 10 if sens == t('sens_media') else 20
        if anterior and plataforma == self.canal.plataforma:
            if plataforma == 'kick':
                original = self.canal.limiar_db
                sens_original = t('sens_alta') if original <= 5 else t('sens_media') if original <= 7 else t('sens_baixa')
                if sens == sens_original:
                    if 'limiar_db' in anterior:
                        novo_canal['limiar_db'] = anterior['limiar_db']
                    else:
                        novo_canal.pop('limiar_db', None)
            else:
                original = self.canal.minimo_absoluto
                if original is None:
                    original = carregar_config(ARQUIVO_CANAIS_TOML).parametros.minimo_absoluto
                sens_original = t('sens_alta') if original <= 5 else t('sens_media') if original <= 10 else t('sens_baixa')
                if sens == sens_original:
                    if 'minimo_absoluto' in anterior:
                        novo_canal['minimo_absoluto'] = anterior['minimo_absoluto']
                    else:
                        novo_canal.pop('minimo_absoluto', None)
        perfis_txt = self.entry_perfil.get().strip()
        lista_perfis = [p.strip() for p in perfis_txt.replace(';', ',').split(',') if p.strip()]
        novo_canal.pop('perfil', None)
        novo_canal.pop('perfis', None)
        if len(lista_perfis) == 1:
            novo_canal['perfil'] = lista_perfis[0]
        elif len(lista_perfis) > 1:
            novo_canal['perfis'] = lista_perfis
        if indice is None:
            canais.append(novo_canal)
        else:
            canais[indice] = novo_canal
        self.tela_canais._escrever_toml(dados)
        self.tela_canais._carregar_canais()
        self.destroy()


class TelaCanais:
    def _adicionar_linha_tabela(self, row, canal):
        if canal.plataforma == 'kick':
            sens = t('sens_alta') if canal.limiar_db <= 5 else t('sens_media') if canal.limiar_db <= 7 else t('sens_baixa')
        else:
            minimo = (canal.minimo_absoluto if canal.minimo_absoluto is not None else
                      carregar_config(ARQUIVO_CANAIS_TOML).parametros.minimo_absoluto)
            sens = t('sens_alta') if minimo <= 5 else t('sens_media') if minimo <= 10 else t('sens_baixa')
        hashtags = canal.hashtags_obrigatorias or '-'
        perfil_txt = ', '.join(canal.perfis) if canal.perfis else canal.perfil or '-'
        plataforma = {'youtube': 'YouTube', 'twitch': 'Twitch', 'kick': 'Kick'}.get(
            canal.plataforma, canal.plataforma.capitalize())
        vals = [(plataforma, 90), (canal.canal, 130), (perfil_txt, 130),
                (sens, 110), (hashtags, 170), ('', 70)]
        for col, (texto, largura) in enumerate(vals):
            lbl = ctk.CTkLabel(
                self.frame_tabela, text=texto, width=largura, anchor='w',
                font=ctk.CTkFont(size=11),
                image=icone('preto', 14) if not texto and col == len(vals) - 1 else None,
                compound='left', wraplength=largura, justify='left')
            lbl.grid(row=row, column=col, padx=8, pady=3, sticky='w')
        frame_acoes = ctk.CTkFrame(self.frame_tabela, fg_color='transparent')
        frame_acoes.grid(row=row, column=len(vals), padx=8, pady=3)
        ctk.CTkButton(frame_acoes, text='', image=icone('lapis', 16), width=30, height=28,
                      command=lambda c=canal: self._editar_canal(c)).pack(side='left', padx=2)
        ctk.CTkButton(frame_acoes, text='', image=icone('lixeira', 16), width=30, height=28,
                      fg_color=COR_VERMELHO, hover_color='#c0392b',
                      command=lambda c=canal: self._remover_canal(c)).pack(side='left', padx=2)

    def _remover_canal_confirmado(self, canal):
        import tomllib
        from clipador_youtube import normalizar_canal

        with ARQUIVO_CANAIS_TOML.open('rb') as f:
            dados = tomllib.load(f)
        restantes = []
        for c in dados.get('canais', []):
            mesma_plataforma = c.get('plataforma', '').lower() == canal.plataforma.lower()
            if mesma_plataforma and canal.plataforma == 'youtube':
                mesmo_canal = normalizar_canal(c.get('canal', '')) == normalizar_canal(canal.canal)
            else:
                mesmo_canal = c.get('canal', '').lower() == canal.canal.lower()
            if not (mesma_plataforma and mesmo_canal):
                restantes.append(c)
        dados['canais'] = restantes
        self._escrever_toml(dados)
        self._carregar_canais()

    def _ver_ao_vivo(self):
        # Only the two nested code objects replace their compiled originals.
        cfg = None

        def verificar_canal(canal_config):
            from clipador_youtube import url_origem
            try:
                cmd = cfg.binarios.streamlink + [
                    '--json', url_origem(canal_config.plataforma, canal_config.canal)]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                if proc.returncode == 0:
                    data = json.loads(proc.stdout)
                    streams = data.get('streams', {})
                    if streams:
                        melhor = list(streams.keys())[-1]
                        categoria = streams[melhor].get('category', '-')
                        return t('online'), categoria
                    return t('offline'), '-'
                return t('erro'), proc.stderr[:50]
            except subprocess.TimeoutExpired:
                return t('erro'), 'timeout'
            except Exception as e:
                return t('erro'), str(e)[:50]

        def _atualizar_linha_resultado(frame, resultados, cfg):
            try:
                if not frame.winfo_exists():
                    return
            except Exception:
                return
            for widget in frame.winfo_children():
                widget.destroy()
            for c in cfg.canais:
                if c.canal not in resultados:
                    continue
                status, cat = resultados[c.canal]
                cor = (COR_VERDE if status == t('online') else
                       COR_VERMELHO if status == t('offline') else COR_AMARELO)
                frame_item = ctk.CTkFrame(frame, fg_color='transparent')
                frame_item.pack(fill='x', pady=2)
                plataforma = {'youtube': 'YouTube', 'twitch': 'Twitch', 'kick': 'Kick'}.get(
                    c.plataforma, c.plataforma.capitalize())
                ctk.CTkLabel(frame_item, text=f'{plataforma} / {c.canal}', width=200,
                             anchor='w', wraplength=200, justify='left').pack(side='left', padx=10)
                ctk.CTkLabel(frame_item, text=status, width=80, text_color=cor,
                             font=ctk.CTkFont(weight='bold')).pack(side='left', padx=10)
                ctk.CTkLabel(frame_item, text=cat, width=150, anchor='w',
                             wraplength=150, justify='left').pack(side='left', padx=10)

        return verificar_canal, _atualizar_linha_resultado


REPLACEMENTS = {
    'DialogCanal._criar_widgets': 'DialogCanal._criar_widgets',
    'DialogCanal._preencher_dados': 'DialogCanal._preencher_dados',
    'DialogCanal._salvar': 'DialogCanal._salvar',
    'TelaCanais._adicionar_linha_tabela': 'TelaCanais._adicionar_linha_tabela',
    'TelaCanais._remover_canal_confirmado': 'TelaCanais._remover_canal_confirmado',
    'TelaCanais._ver_ao_vivo.<locals>.verificar_canal':
        'TelaCanais._ver_ao_vivo.<locals>.verificar_canal',
    'TelaCanais._ver_ao_vivo.<locals>._atualizar_linha_resultado':
        'TelaCanais._ver_ao_vivo.<locals>._atualizar_linha_resultado',
}


CONSTANT_TRANSFORMS = {
    'clipador.gui.i18n': {
        'Encontrar canais ao vivo': 'Encontrar canais ao vivo na Twitch',
        'Find live channels': 'Find live channels on Twitch',
        'Adicione os canais que você tem autorização para cortar (Twitch/Kick).':
            'Adicione os canais que você tem autorização para cortar (Twitch/Kick/YouTube).',
        'Add the channels you are authorized to clip (Twitch/Kick).':
            'Add the channels you are authorized to clip (Twitch/Kick/YouTube).',
    },
}
