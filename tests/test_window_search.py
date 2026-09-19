"""Testes do bloqueio da busca por modo, na janela de verdade.

``test_find_bar.py`` cobre a regra isolada (``config.editing_available``). Aqui
o que se verifica é a ligação: as ações do menu realmente desabilitam no modo
de leitura, e a barra não fica aberta operando sobre um editor escondido.

Precisa da janela completa, que sobe o Chromium — por isso é um arquivo
separado, e não parte da suíte leve.
"""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("PyQt6.QtWebEngineCore")

from PyQt6 import QtWebEngineWidgets  # noqa: F401,E402  (antes do QApplication)
from PyQt6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PyQt6.QtGui import QTextCursor  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from edgemd.config import AppConfig  # noqa: E402
from edgemd.render import MarkdownRenderer  # noqa: E402
from edgemd.window import MainWindow  # noqa: E402




@pytest.fixture
def janela(qapp, tmp_path):
    """Janela com um documento de exemplo aberto."""
    origem = tmp_path / "nota.md"
    origem.write_text(
        "# Título\n\nalfa beta alfa gama\n\nMermaid e Mermaid de novo\n",
        encoding="utf-8",
    )

    win = MainWindow(
        AppConfig(settings_path=tmp_path / "cfg.ini"), MarkdownRenderer()
    )
    win.open_paths([str(origem)])
    yield win

    win._force_close = True
    win.close()
    win.deleteLater()
    # Sem processar as exclusões adiadas, o perfil do WebEngine é liberado antes
    # das páginas e o Qt avisa na saída da suíte.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


class TestAcoesPorModo:
    def test_leitura_desabilita_a_busca(self, janela):
        janela.set_view_mode("preview")
        assert janela.action_find.isEnabled() is False
        assert janela.action_replace.isEnabled() is False
        assert janela.action_find_next.isEnabled() is False
        assert janela.action_find_previous.isEnabled() is False

    @pytest.mark.parametrize("modo", ["split", "editor"])
    def test_edicao_habilita_a_busca(self, janela, modo):
        janela.set_view_mode(modo)
        assert janela.action_find.isEnabled() is True
        assert janela.action_replace.isEnabled() is True

    def test_sem_aba_desabilita_mesmo_em_edicao(self, janela):
        janela.set_view_mode("editor")
        janela.close_all_tabs()
        janela._update_actions()
        assert janela.action_find.isEnabled() is False


class TestAbertura:
    def test_abre_a_barra_em_modo_de_edicao(self, janela):
        janela.set_view_mode("split")
        janela.action_find.trigger()
        tab = janela.current_tab
        assert tab is not None
        assert tab.is_searching

    def test_abre_com_substituicao(self, janela):
        janela.set_view_mode("split")
        janela.action_replace.trigger()
        tab = janela.current_tab
        assert tab is not None
        assert tab.find_bar.replace_visible()

    def test_no_modo_de_leitura_avisa_em_vez_de_abrir(self, janela):
        """O aviso na barra de status explica por que o atalho não abriu nada."""
        janela.set_view_mode("preview")
        janela.open_find()
        tab = janela.current_tab
        assert tab is not None
        assert not tab.is_searching
        assert "edição" in janela._status_message.text().lower()

    def test_sair_da_edicao_fecha_a_barra(self, janela):
        """Deixá-la aberta num editor escondido seria um campo ativo às cegas."""
        janela.set_view_mode("split")
        janela.open_replace()
        tab = janela.current_tab
        assert tab is not None
        assert tab.is_searching

        janela.set_view_mode("preview")
        assert not tab.is_searching
        assert tab.editor._search_ranges == []

    def test_f3_com_a_barra_fechada_a_abre(self, janela):
        janela.set_view_mode("split")
        tab = janela.current_tab
        assert tab is not None
        tab.close_search()

        janela.action_find_next.trigger()
        assert tab.is_searching


class TestBuscaPontaAPonta:
    def test_selecao_vira_termo_inicial(self, janela):
        """Ctrl+F com uma palavra selecionada já busca por ela."""
        janela.set_view_mode("editor")
        tab = janela.current_tab
        assert tab is not None

        texto = tab.editor.toPlainText()
        inicio = texto.index("beta")
        cursor = QTextCursor(tab.editor.document())
        cursor.setPosition(inicio)
        cursor.setPosition(inicio + 4, QTextCursor.MoveMode.KeepAnchor)
        tab.editor.setTextCursor(cursor)

        janela.open_find()
        assert tab.find_bar.query == "beta"
        assert len(tab.search.matches) == 1

    def test_substituir_no_editor_marca_alteracao(self, janela):
        janela.set_view_mode("editor")
        tab = janela.current_tab
        assert tab is not None

        termo = "alfa"
        tab.find_bar.search_input.setText(termo)
        tab.search._on_search_changed(termo, tab.find_bar.options)
        assert len(tab.search.matches) == 2

        tab.search.replace_all("omega")
        assert tab.editor.toPlainText().count("omega") == 2
        assert tab.is_dirty is True
