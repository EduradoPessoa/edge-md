"""Testes de inserção de link, imagem e emoji no editor e na janela.

Cobre o que a lógica pura não alcança: o texto que sai no documento, o efeito
no histórico de desfazer, e as ações da barra de ferramentas.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtWebEngineCore")

from PyQt6 import QtWebEngineWidgets  # noqa: F401,E402  (antes do QApplication)
from PyQt6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PyQt6.QtGui import QTextCursor  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog  # noqa: E402

from edgemd.config import AppConfig  # noqa: E402
from edgemd.editor_widget import MarkdownEditor  # noqa: E402
from edgemd.insert_dialogs import ImageDialog, LinkDialog  # noqa: E402
from edgemd.render import MarkdownRenderer  # noqa: E402
from edgemd.window import MainWindow  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\nfalso"


# --------------------------------------------------------------------------
# Editor
# --------------------------------------------------------------------------

@pytest.fixture
def editor(qapp):
    widget = MarkdownEditor(theme="dark")
    widget.setPlainText("")
    yield widget
    widget.deleteLater()


class TestInsercaoNoEditor:
    def test_link(self, editor):
        editor.insert_markdown_link("Documentação", "https://exemplo.com")
        assert editor.toPlainText() == "[Documentação](https://exemplo.com)"

    def test_imagem(self, editor):
        editor.insert_image("diagrama", "imagens/fluxo.png")
        assert editor.toPlainText() == "![diagrama](imagens/fluxo.png)"

    def test_emoji(self, editor):
        editor.insert_emoji("🚀")
        assert editor.toPlainText() == "🚀"

    def test_emoji_apos_palavra_ganha_espaco(self, editor):
        """Colar emoji no meio de uma palavra quase nunca é o que se quer."""
        editor.setPlainText("pronto")
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        editor.setTextCursor(cursor)

        editor.insert_emoji("✅")
        assert editor.toPlainText() == "pronto ✅"

    def test_emoji_no_inicio_nao_ganha_espaco(self, editor):
        editor.insert_emoji("🚀")
        assert editor.toPlainText() == "🚀"

    def test_emoji_apos_espaco_nao_duplica(self, editor):
        editor.setPlainText("pronto ")
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        editor.setTextCursor(cursor)

        editor.insert_emoji("✅")
        assert editor.toPlainText() == "pronto ✅"

    def test_link_substitui_a_selecao(self, editor):
        editor.setPlainText("veja isto aqui")
        cursor = editor.textCursor()
        cursor.setPosition(5)
        cursor.setPosition(9, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)

        editor.insert_markdown_link("isto", "https://x.com")
        assert editor.toPlainText() == "veja [isto](https://x.com) aqui"

    def test_insercao_e_um_passo_de_desfazer(self, editor):
        editor.insert_image("a", "a.png")
        editor.undo()
        assert editor.toPlainText() == ""

    def test_imagem_no_historico_junto_com_o_texto(self, editor):
        editor.setPlainText("antes ")
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        editor.setTextCursor(cursor)

        editor.insert_image("a", "a.png")
        editor.undo()
        assert editor.toPlainText() == "antes "


# --------------------------------------------------------------------------
# Diálogos
# --------------------------------------------------------------------------

class TestLinkDialog:
    def test_prefill(self, qapp):
        dialogo = LinkDialog(text="Nota", url="https://x.com")
        try:
            assert dialogo.text_input.text() == "Nota"
            assert dialogo.url_input.text() == "https://x.com"
        finally:
            dialogo.deleteLater()

    def test_texto_vazio_cai_para_o_endereco(self, qapp):
        dialogo = LinkDialog(text="  ", url="https://x.com")
        try:
            assert dialogo.link_text == "https://x.com"
        finally:
            dialogo.deleteLater()

    def test_ok_desligado_sem_endereco(self, qapp):
        dialogo = LinkDialog(text="Nota", url="")
        try:
            assert not dialogo._ok.isEnabled()
            dialogo.url_input.setText("https://x.com")
            assert dialogo._ok.isEnabled()
        finally:
            dialogo.deleteLater()

    def test_so_espaco_nao_libera(self, qapp):
        dialogo = LinkDialog(url="   ")
        try:
            assert not dialogo._ok.isEnabled()
        finally:
            dialogo.deleteLater()

    def test_ask_devolve_none_ao_cancelar(self, qapp, monkeypatch):
        monkeypatch.setattr(
            LinkDialog, "exec", lambda self: QDialog.DialogCode.Rejected
        )
        assert LinkDialog.ask(None, text="a", url="b") is None

    def test_ask_devolve_o_par(self, qapp, monkeypatch):
        monkeypatch.setattr(
            LinkDialog, "exec", lambda self: QDialog.DialogCode.Accepted
        )
        assert LinkDialog.ask(None, text="Nota", url="https://x.com") == (
            "Nota",
            "https://x.com",
        )


class TestImageDialog:
    def test_sem_copia_esconde_a_opcao(self, qapp):
        dialogo = ImageDialog(alt="a", can_copy=False)
        try:
            assert not dialogo.copy_check.isVisible()
            assert dialogo.copy_external is False
        finally:
            dialogo.deleteLater()

    def test_com_copia_marcada_por_padrao(self, qapp, tmp_path):
        """Copiar é o padrão: sem isso o documento guarda caminho desta máquina."""
        dialogo = ImageDialog(alt="a", can_copy=True)
        try:
            dialogo.copy_check.setVisible(True)
            assert dialogo.copy_check.isChecked() is True
            assert dialogo.copy_external is True
        finally:
            dialogo.deleteLater()

    def test_alt_editavel(self, qapp):
        dialogo = ImageDialog(alt="figura")
        try:
            dialogo.alt_input.setText("  diagrama de rede  ")
            assert dialogo.alt == "diagrama de rede"
        finally:
            dialogo.deleteLater()

    def test_ask_devolve_none_ao_cancelar(self, qapp, monkeypatch):
        monkeypatch.setattr(
            ImageDialog, "exec", lambda self: QDialog.DialogCode.Rejected
        )
        assert ImageDialog.ask(None, alt="a") is None


# --------------------------------------------------------------------------
# Janela
# --------------------------------------------------------------------------

@pytest.fixture
def janela(qapp, tmp_path):
    """Documento numa pasta própria, com uma pasta de "downloads" ao lado.

    A separação importa: só uma imagem **fora** da pasta do documento faz a
    cópia entrar em cena. Com tudo em ``tmp_path``, a imagem já estaria dentro e
    o caminho relativo bastaria.
    """
    notas = tmp_path / "notas"
    notas.mkdir()
    origem = notas / "nota.md"
    origem.write_text("# Título\n\nTexto.\n", encoding="utf-8")

    (tmp_path / "Downloads").mkdir()

    win = MainWindow(
        AppConfig(settings_path=tmp_path / "cfg.ini"), MarkdownRenderer()
    )
    win.open_paths([str(origem)])
    win.set_view_mode("editor")
    yield win

    win._force_close = True
    win.close()
    win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


class TestBarraDeFerramentas:
    def test_acoes_existem(self, janela):
        assert janela.action_image is not None
        assert janela.action_emoji is not None
        assert janela.action_link is not None

    def test_estao_na_barra(self, janela):
        nomes = {a.text() for a in janela.toolbar.actions()}
        assert "Link" in nomes
        assert "Imagem…" in nomes
        assert "Emoji…" in nomes

    def test_tem_icone(self, janela):
        for acao in (janela.action_image, janela.action_emoji, janela.action_link):
            assert not acao.icon().isNull(), acao.text()

    def test_desabilitadas_sem_aba(self, janela):
        janela.close_all_tabs()
        janela._update_actions()
        assert not janela.action_image.isEnabled()
        assert not janela.action_emoji.isEnabled()


class TestInsercaoPelaJanela:
    def test_link_inserido(self, janela, monkeypatch):
        monkeypatch.setattr(
            LinkDialog, "ask", staticmethod(lambda *a, **k: ("Nota", "https://x.com"))
        )
        janela.insert_link()

        tab = janela.current_tab
        assert "[Nota](https://x.com)" in tab.editor.toPlainText()

    def test_link_cancelado_nao_altera(self, janela, monkeypatch):
        antes = janela.current_tab.editor.toPlainText()
        monkeypatch.setattr(LinkDialog, "ask", staticmethod(lambda *a, **k: None))
        janela.insert_link()
        assert janela.current_tab.editor.toPlainText() == antes

    def test_selecao_vira_texto_do_link(self, janela, monkeypatch):
        tab = janela.current_tab
        capturado: dict = {}

        def falso_ask(parent, *, text="", url=""):
            capturado["text"] = text
            return (text, "https://x.com")

        monkeypatch.setattr(LinkDialog, "ask", staticmethod(falso_ask))

        texto = tab.editor.toPlainText()
        inicio = texto.index("Título")
        cursor = QTextCursor(tab.editor.document())
        cursor.setPosition(inicio)
        cursor.setPosition(inicio + 6, QTextCursor.MoveMode.KeepAnchor)
        tab.editor.setTextCursor(cursor)

        janela.insert_link()
        assert capturado["text"] == "Título"

    def test_emoji_inserido(self, janela):
        tab = janela.current_tab
        janela._on_emoji_chosen("🚀")
        assert "🚀" in tab.editor.toPlainText()

    def test_sugere_url_do_clipboard(self, janela):
        QApplication.clipboard().setText("https://exemplo.com/pagina")
        assert janela._clipboard_url() == "https://exemplo.com/pagina"

    def test_nao_sugere_texto_qualquer(self, janela):
        QApplication.clipboard().setText("apenas um texto")
        assert janela._clipboard_url() == ""

    def test_nao_sugere_multilinha(self, janela):
        QApplication.clipboard().setText("https://a.com\nhttps://b.com")
        assert janela._clipboard_url() == ""

    def test_imagem_copiada_e_inserida(self, janela, tmp_path, monkeypatch):
        tab = janela.current_tab
        documento = tab.path

        baixados = tmp_path / "Downloads"
        figura = baixados / "grafico.png"
        figura.write_bytes(PNG)

        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            staticmethod(lambda *a, **k: (str(figura), "")),
        )
        monkeypatch.setattr(
            ImageDialog, "ask", staticmethod(lambda *a, **k: ("gráfico de vendas", True))
        )

        janela.insert_image()

        assert "![gráfico de vendas](imagens/grafico.png)" in tab.editor.toPlainText()
        copiada = documento.parent / "imagens" / "grafico.png"
        assert copiada.is_file()
        assert copiada.read_bytes() == PNG

    def test_imagem_sem_copiar_usa_absoluto(self, janela, tmp_path, monkeypatch):
        tab = janela.current_tab
        baixados = tmp_path / "Downloads"
        figura = baixados / "grafico.png"
        figura.write_bytes(PNG)

        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            staticmethod(lambda *a, **k: (str(figura), "")),
        )
        monkeypatch.setattr(
            ImageDialog, "ask", staticmethod(lambda *a, **k: ("g", False))
        )

        janela.insert_image()

        texto = tab.editor.toPlainText()
        assert "Downloads" in texto
        assert not (tab.path.parent / "imagens").exists()

    def test_imagem_cancelada_nao_altera(self, janela, monkeypatch):
        antes = janela.current_tab.editor.toPlainText()
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", ""))
        )
        janela.insert_image()
        assert janela.current_tab.editor.toPlainText() == antes

    def test_dialogo_de_imagem_cancelado_nao_altera(self, janela, tmp_path, monkeypatch):
        tab = janela.current_tab
        antes = tab.editor.toPlainText()
        figura = tmp_path / "f.png"
        figura.write_bytes(PNG)

        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            staticmethod(lambda *a, **k: (str(figura), "")),
        )
        monkeypatch.setattr(ImageDialog, "ask", staticmethod(lambda *a, **k: None))

        janela.insert_image()
        assert tab.editor.toPlainText() == antes
