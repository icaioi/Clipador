"""Source factory retaining the frozen installer's exact closure contract."""
def callback_factory(btn_fechar,label_status,progress,seguro,self,ui):
    def rodar_instalacao():
        try:
            from clipador_componentes import instalar
            seguro(lambda:label_status.configure(text=t('instalando_exec'),wraplength=450))
            seguro(lambda:progress.set(0.1))
            def registrar(texto):
                seguro(lambda txt=texto.splitlines()[0][:160]:label_status.configure(text=txt))
            instalar(registrar)
            seguro(lambda:label_status.configure(text=t('chromium_ok'),**kw('chromium_ok')))
            seguro(lambda:progress.set(1))
        except Exception as error:
            mensagem=str(error)
            def mostrar_erro():
                label_status.master.geometry('500x340')
                label_status.configure(text=mensagem,wraplength=450,image=icone('erro'),compound='left')
                progress.set(0)
            seguro(mostrar_erro)
        finally:
            seguro(lambda:btn_fechar.configure(state='normal'))
            ui(self.atualizar_status)
    return rodar_instalacao
