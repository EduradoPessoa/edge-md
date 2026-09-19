"""Testes do fluxo de modelos na janela.

A lógica de armazenamento está coberta em ``test_templates.py``. Aqui o que se
verifica é a ligação: o documento novo nasce com o conteúdo do modelo, o
modelo padrão é respeitado, e salvar como modelo grava o que está na tela.
"""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("PyQt6.QtWebEngineCore")

from PyQt6 import QtWebEngineWidgets  # noqa: F401,E402  (antes do QApplication)
from PyQt6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox  # noqa: E402

from edgemd import templates  # noqa: E402
from edgemd.config import AppConfig  # noqa: E402
from edgemd.render import MarkdownRenderer  # noqa: E402
from edgemd.template_picker import TemplatePicker  # noqa: E402
from edgemd.window import MainWindow  # noqa: E402


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    destino = tmp_path / "templates"
    destino.mkdir()
    monkeypatch.setattr(templates, "templates_dir", lambda: destino)
    return destino


@pytest.fixture
def janela(qapp, tmp_path, pasta):
    """Janela com um documento aberto.

    A aba já existe para os testes que operam sobre o documento atual; os que
    criam arquivos novos chamam ``new_file()`` e trabalham na aba que nasce.
    """
    origem = tmp_path / "nota.md"
    origem.write_text("# nota\n", encoding="utf-8")

    win = MainWindow(
        AppConfig(settings_path=tmp_path / "cfg.ini"), MarkdownRenderer()
    )
    win.open_paths([str(origem)])
    yield win

    win._force_close = True
    win.close()
    win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


class TestDocumentoNovo:
    def test_em_branco_por_padrao(self, janela):
        janela.new_file()
        assert janela.current_tab is not None
        assert janela.current_tab.editor.toPlainText() == "# \n\n"

    def test_em_branco_nao_pede_confirmacao(self, janela):
        """O modelo é ponto de partida, não alteração a salvar."""
        janela.new_file()
        assert janela.current_tab.is_dirty is False

    def test_cursor_depois_do_cerquilha(self, janela):
        janela.new_file()
        assert janela.current_tab.editor.textCursor().position() == 2

    def test_a_partir_de_modelo_do_usuario(self, janela, pasta):
        templates.save("Meu", "# Meu título\n\ncorpo do modelo\n")
        janela.new_file(template="Meu")

        texto = janela.current_tab.editor.toPlainText()
        assert "corpo do modelo" in texto
        assert janela.current_tab.is_dirty is False

    def test_a_partir_de_modelo_embutido(self, janela):
        janela.new_file(template="Diário")
        texto = janela.current_tab.editor.toPlainText()
        assert "O que aprendi" in texto

    def test_modelo_expande_a_data(self, janela):
        from datetime import datetime

        templates.save("Com data", "# Feito em {data}\n\n")
        janela.new_file(template="Com data")
        assert datetime.now().strftime("%d/%m/%Y") in janela.current_tab.editor.toPlainText()

    def test_modelo_inexistente_cai_para_branco(self, janela):
        janela.new_file(template="não existe")
        assert janela.current_tab.editor.toPlainText() == "# \n\n"

    def test_cursor_vai_para_o_ponto_do_modelo(self, janela, pasta):
        templates.save("Cursor", "# Título\n\n## Seção\n")
        janela.new_file(template="Cursor")
        # Logo depois do título, não no fim do arquivo.
        assert janela.current_tab.editor.textCursor().position() == len("# Título\n")


class TestModeloPadrao:
    def test_padrao_em_branco(self, janela):
        assert janela.config.default_template == ""
        janela.new_file()
        assert janela.current_tab.editor.toPlainText() == "# \n\n"

    def test_padrao_configurado(self, janela, pasta):
        templates.save("Ata", "# Ata de reunião\n\n")
        janela.config.default_template = "Ata"
        janela.new_file()
        assert "Ata de reunião" in janela.current_tab.editor.toPlainText()

    def test_padrao_vazio_forca_branco(self, janela, pasta):
        templates.save("Ata", "# Ata\n\n")
        janela.config.default_template = "Ata"
        janela.new_file(template="")
        assert janela.current_tab.editor.toPlainText() == "# \n\n"

    def test_padrao_apagado_cai_para_branco(self, janela, pasta):
        """Apagar o modelo não pode impedir a criação de arquivos."""
        templates.save("Some", "# x\n\n")
        janela.config.default_template = "Some"
        templates.delete("Some")

        janela.new_file()
        assert janela.current_tab is not None
        assert janela.current_tab.editor.toPlainText() == "# \n\n"

    def test_pergunta_desligada_por_padrao(self, janela):
        assert janela.config.ask_template_on_new is False

    def test_pergunta_ligada_usa_o_dialogo(self, janela, pasta, monkeypatch):
        templates.save("Escolhido", "# do diálogo\n\n")
        janela.config.ask_template_on_new = True

        monkeypatch.setattr(
            TemplatePicker, "ask",
            staticmethod(lambda *a, **k: templates.find("Escolhido")),
        )
        janela.new_file()
        assert "do diálogo" in janela.current_tab.editor.toPlainText()

    def test_cancelar_a_pergunta_nao_cria_aba(self, janela, monkeypatch):
        janela.config.ask_template_on_new = True
        monkeypatch.setattr(TemplatePicker, "ask", staticmethod(lambda *a, **k: None))

        antes = janela.tabs.count()
        janela.new_file()
        assert janela.tabs.count() == antes


class TestSalvarComoModelo:
    def test_grava_o_conteudo_atual(self, janela, pasta, monkeypatch):
        tab = janela.current_tab
        tab.editor.setPlainText("# Reunião semanal\n\npauta\n")

        monkeypatch.setattr(
            QInputDialog, "getText",
            staticmethod(lambda *a, **k: ("Reunião semanal", True)),
        )
        janela.save_as_template()

        modelo = templates.find("Reunião semanal")
        assert modelo is not None
        assert "pauta" in modelo.content

    def test_cancelar_nao_grava(self, janela, pasta, monkeypatch):
        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False))
        )
        janela.save_as_template()
        assert templates.user_templates() == []

    def test_nome_vazio_nao_grava(self, janela, pasta, monkeypatch):
        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *a, **k: ("   ", True))
        )
        janela.save_as_template()
        assert templates.user_templates() == []

    def test_embutido_ganha_copia(self, janela, pasta, monkeypatch):
        """Sobrescrever o que veio com o app não é possível: vira cópia."""
        tab = janela.current_tab
        tab.editor.setPlainText("# meu diário\n")

        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *a, **k: ("Diário", True))
        )
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))

        janela.save_as_template()

        assert templates.find("Diário (meu)") is not None
        # O embutido continua intacto.
        assert "O que aprendi" in templates.find("Diário").content

    def test_sobrescrever_pede_confirmacao(self, janela, pasta, monkeypatch):
        templates.save("Meu", "# antigo\n")
        tab = janela.current_tab
        tab.editor.setPlainText("# novo\n")

        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *a, **k: ("Meu", True))
        )
        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
        )
        janela.save_as_template()
        assert "antigo" in templates.find("Meu").content

    def test_sobrescrever_confirmado(self, janela, pasta, monkeypatch):
        templates.save("Meu", "# antigo\n")
        janela.current_tab.editor.setPlainText("# novo\n")

        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *a, **k: ("Meu", True))
        )
        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
        )
        janela.save_as_template()
        assert "novo" in templates.find("Meu").content

    def test_sem_aba_nao_faz_nada(self, janela, pasta, monkeypatch):
        janela.close_all_tabs()
        monkeypatch.setattr(
            QInputDialog, "getText",
            staticmethod(lambda *a, **k: pytest.fail("não deveria perguntar")),
        )
        janela.save_as_template()

    def test_sugere_o_nome_do_arquivo(self, janela, tmp_path, pasta, monkeypatch):
        origem = tmp_path / "ata-de-reuniao.md"
        origem.write_text("# x\n", encoding="utf-8")
        janela.open_paths([str(origem)])

        capturado: dict = {}

        def falso_get_text(parent, titulo, texto, **kwargs):
            capturado["sugestao"] = kwargs.get("text")
            return ("", False)

        monkeypatch.setattr(QInputDialog, "getText", staticmethod(falso_get_text))
        janela.save_as_template()
        assert capturado["sugestao"] == "ata-de-reuniao"


class TestAcoes:
    def test_acoes_existem(self, janela):
        assert janela.action_new_from_template is not None
        assert janela.action_save_as_template is not None
        assert janela.action_manage_templates is not None

    def test_tem_icone(self, janela):
        for acao in (
            janela.action_new_from_template,
            janela.action_save_as_template,
        ):
            assert not acao.icon().isNull(), acao.text()

    def test_salvar_como_modelo_exige_aba(self, janela):
        janela.close_all_tabs()
        janela._update_actions()
        assert not janela.action_save_as_template.isEnabled()

    def test_novo_com_modelo_nao_exige_aba(self, janela):
        """Criar arquivo é justamente o que se faz quando não há nenhum aberto."""
        janela.close_all_tabs()
        janela._update_actions()
        assert janela.action_new_from_template.isEnabled()
        assert janela.action_new.isEnabled()

    def test_novo_a_partir_de_modelo_usa_o_dialogo(self, janela, pasta, monkeypatch):
        templates.save("Escolhido", "# escolhido\n\n")
        monkeypatch.setattr(
            TemplatePicker, "ask",
            staticmethod(lambda *a, **k: templates.find("Escolhido")),
        )
        janela.new_from_template()
        assert "escolhido" in janela.current_tab.editor.toPlainText()

    def test_novo_a_partir_de_modelo_cancelado(self, janela, monkeypatch):
        monkeypatch.setattr(TemplatePicker, "ask", staticmethod(lambda *a, **k: None))
        antes = janela.tabs.count()
        janela.new_from_template()
        assert janela.tabs.count() == antes


class TestSeletor:
    def test_lista_todos_os_modelos(self, qapp, pasta):
        templates.save("Meu", "# x\n")
        seletor = TemplatePicker()
        try:
            # Em branco + do usuário + embutidos.
            esperado = 1 + 1 + len(templates.builtin_templates())
            assert seletor.list.count() == esperado
        finally:
            seletor.deleteLater()

    def test_primeiro_e_em_branco(self, qapp, pasta):
        seletor = TemplatePicker()
        try:
            assert seletor.list.item(0).text() == "Em branco"
        finally:
            seletor.deleteLater()

    def test_previa_mostra_o_conteudo(self, qapp, pasta):
        templates.save("Meu", "# conteúdo único\n")
        seletor = TemplatePicker()
        try:
            seletor.list.setCurrentRow(1)
            assert "conteúdo único" in seletor.preview.toPlainText()
        finally:
            seletor.deleteLater()

    def test_excluir_desabilitado_para_embutido(self, qapp, pasta):
        seletor = TemplatePicker()
        try:
            indice = next(
                i for i in range(seletor.list.count())
                if seletor.list.item(i).text() == "Diário"
            )
            seletor.list.setCurrentRow(indice)
            assert not seletor.delete_button.isEnabled()
        finally:
            seletor.deleteLater()

    def test_excluir_habilitado_para_do_usuario(self, qapp, pasta):
        templates.save("Meu", "# x\n")
        seletor = TemplatePicker()
        try:
            seletor.list.setCurrentRow(1)
            assert seletor.delete_button.isEnabled()
        finally:
            seletor.deleteLater()

    def test_escolha_devolvida(self, qapp, pasta):
        templates.save("Meu", "# x\n")
        seletor = TemplatePicker()
        try:
            seletor.list.setCurrentRow(1)
            seletor.accept()
            assert seletor.chosen is not None
            assert seletor.chosen.name == "Meu"
        finally:
            seletor.deleteLater()

    def test_ask_devolve_none_ao_cancelar(self, qapp, monkeypatch):
        from PyQt6.QtWidgets import QDialog

        monkeypatch.setattr(
            TemplatePicker, "exec", lambda self: QDialog.DialogCode.Rejected
        )
        assert TemplatePicker.ask() is None
