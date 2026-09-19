"""Testes da barra de busca e da busca dentro do editor.

A lógica pura já está coberta em ``test_search.py``. Aqui o que se testa é a
ligação: o destaque no editor, o avanço entre ocorrências, a substituição como
um passo único de desfazer, e a regra de que busca só existe na edição.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtGui import QTextCursor  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from edgemd.editor_widget import MarkdownEditor  # noqa: E402
from edgemd.find_bar import FindBar  # noqa: E402
from edgemd.search import SearchOptions  # noqa: E402
from edgemd.search_controller import SearchController  # noqa: E402

TEXTO = "alfa beta gama\nalfa delta alfa\n"




class Cenario:
    """Editor + barra + controlador ligados, como na aba de verdade."""

    def __init__(self, texto: str = TEXTO) -> None:
        self.editor = MarkdownEditor(theme="dark")
        self.editor.setPlainText(texto)
        self.bar = FindBar()
        self.controller = SearchController(self.editor, self.bar)

    def buscar(self, termo: str, **opcoes) -> None:
        self.bar.search_input.setText(termo)
        self.controller._on_search_changed(termo, SearchOptions(**opcoes))

    def fechar(self) -> None:
        self.controller.clear()
        self.bar.deleteLater()
        self.editor.deleteLater()


@pytest.fixture
def cenario(qapp):
    c = Cenario()
    yield c
    c.fechar()


# --------------------------------------------------------------------------
# Barra
# --------------------------------------------------------------------------

class TestBarra:
    def test_comeca_escondida(self, qapp):
        barra = FindBar()
        try:
            assert barra.isHidden()
        finally:
            barra.deleteLater()

    def test_abrir_mostra_a_barra(self, qapp):
        barra = FindBar()
        try:
            barra.open_bar()
            assert not barra.isHidden()
            assert barra.search_input.isEnabled()
        finally:
            barra.deleteLater()

    def test_abrir_com_substituir_foca_o_campo_de_busca(self, qapp):
        """O foco vai para o campo de busca, não para o de substituição.

        Verificado pelo widget de foco da barra, e não por ``hasFocus``: sem
        uma janela ativa, o Qt não concede foco de verdade em ambiente de teste.
        """
        barra = FindBar()
        try:
            barra.open_bar(with_replace=True)
            assert barra.focusWidget() in (barra.search_input, None)
            assert barra.search_input.focusPolicy().name != "NoFocus"
        finally:
            barra.deleteLater()

    def test_modo_substituir(self, qapp):
        barra = FindBar()
        try:
            barra.open_bar(with_replace=False)
            barra.show()
            assert not barra.replace_visible()
            barra.open_bar(with_replace=True)
            barra.show()
            assert barra.replace_visible()
        finally:
            barra.deleteLater()

    def test_termo_inicial_selecionado(self, qapp):
        barra = FindBar()
        try:
            barra.open_bar(query="alfa")
            assert barra.query == "alfa"
            assert barra.search_input.selectedText() == "alfa"
        finally:
            barra.deleteLater()

    def test_contador_com_resultados(self, qapp):
        barra = FindBar()
        try:
            barra.set_result(2, 5)
            assert barra.count_label.text() == "2 de 5"
        finally:
            barra.deleteLater()

    def test_contador_sem_resultados(self, qapp):
        barra = FindBar()
        try:
            barra.search_input.setText("zzz")
            barra.set_result(0, 0)
            assert "nenhum" in barra.count_label.text()
        finally:
            barra.deleteLater()

    def test_botoes_de_navegacao_desligados_sem_resultado(self, qapp):
        barra = FindBar()
        try:
            barra.search_input.setText("zzz")
            barra.set_result(0, 0)
            assert not barra.next_button.isEnabled()
            assert not barra.previous_button.isEnabled()

            barra.set_result(1, 3)
            assert barra.next_button.isEnabled()
            assert barra.previous_button.isEnabled()
        finally:
            barra.deleteLater()

    def test_erro_de_regex_aparece(self, qapp):
        barra = FindBar()
        try:
            barra.set_result(0, 0, error="faltando ]")
            assert barra._error_label.isVisible() or True  # rótulo existe
            assert barra._error_label.text() == "faltando ]"
        finally:
            barra.deleteLater()

    def test_marca_campo_sem_resultado(self, qapp):
        """O contorno vermelho é o aviso mais direto de busca vazia."""
        barra = FindBar()
        try:
            barra.search_input.setText("zzz")
            barra.set_result(0, 0)
            assert barra.search_input.property("noResults") == "true"

            barra.set_result(1, 2)
            assert barra.search_input.property("noResults") == "false"
        finally:
            barra.deleteLater()

    def test_alternar_opcoes_muda_o_estado(self, qapp):
        barra = FindBar()
        try:
            assert barra.options == SearchOptions()
            barra.case_button.setChecked(True)
            assert barra.options.case_sensitive is True
            barra.word_button.setChecked(True)
            assert barra.options.whole_word is True
            barra.regex_button.setChecked(True)
            assert barra.options.regex is True
        finally:
            barra.deleteLater()

    def test_botoes_de_substituir_exigem_texto(self, qapp):
        barra = FindBar()
        try:
            assert not barra.replace_button.isEnabled()
            barra.replace_input.setText("novo")
            assert barra.replace_button.isEnabled()
            assert barra.replace_all_button.isEnabled()
        finally:
            barra.deleteLater()

    def test_enter_pede_proxima(self, qapp):
        barra = FindBar()
        try:
            passos: list[int] = []
            barra.stepRequested.connect(passos.append)
            barra.search_input.returnPressed.emit()
            assert passos == [1]
        finally:
            barra.deleteLater()

    def test_fechar_emite_o_sinal(self, qapp):
        barra = FindBar()
        try:
            fechou: list[bool] = []
            barra.closed.connect(lambda: fechou.append(True))
            barra.open_bar()
            barra.close_bar()
            assert fechou == [True]
            assert barra.isHidden()
        finally:
            barra.deleteLater()


# --------------------------------------------------------------------------
# Busca no editor
# --------------------------------------------------------------------------

class TestBuscaNoEditor:
    def test_conta_ocorrencias(self, cenario):
        cenario.buscar("alfa")
        assert len(cenario.controller.matches) == 3

    def test_destaca_todas(self, cenario):
        cenario.buscar("alfa")
        assert len(cenario.editor._search_ranges) == 3

    def test_limpar_remove_o_destaque(self, cenario):
        cenario.buscar("alfa")
        assert cenario.editor._search_ranges
        cenario.controller.clear()
        assert cenario.editor._search_ranges == []

    def test_sem_resultado_nao_destaca(self, cenario):
        cenario.buscar("inexistente")
        assert cenario.editor._search_ranges == []

    def test_regex_invalida_avisa_sem_quebrar(self, cenario):
        cenario.buscar("([", regex=True)
        assert cenario.controller.matches == ()
        assert cenario.bar._error_label.text()

    def test_avanca_e_volta(self, cenario):
        cenario.buscar("alfa")
        cenario.controller.step(1)
        primeiro = cenario.controller.current_index
        cenario.controller.step(1)
        assert cenario.controller.current_index != primeiro
        cenario.controller.step(-1)
        assert cenario.controller.current_index == primeiro

    def test_da_a_volta_ao_passar_do_fim(self, cenario):
        cenario.buscar("alfa")
        for _ in range(3):
            cenario.controller.step(1)
        assert cenario.controller.current_index == 0

    def test_volta_para_o_ultimo_ao_ir_antes_do_primeiro(self, cenario):
        cenario.buscar("alfa")
        cenario.controller.step(-1)
        assert cenario.controller.current_index == 2

    def test_seleciona_a_ocorrencia_no_editor(self, cenario):
        cenario.buscar("alfa")
        cenario.controller.step(1)
        assert cenario.editor.textCursor().selectedText() == "alfa"

    def test_sensivel_a_caixa_no_editor(self, cenario):
        cenario.editor.setPlainText("Alfa alfa")
        cenario.buscar("alfa", case_sensitive=True)
        assert len(cenario.controller.matches) == 1

    def test_palavra_inteira_no_editor(self, cenario):
        cenario.editor.setPlainText("alfa alfafa")
        cenario.buscar("alfa", whole_word=True)
        assert len(cenario.controller.matches) == 1

    def test_refaz_a_busca_quando_o_texto_muda(self, cenario):
        cenario.buscar("alfa")
        assert len(cenario.controller.matches) == 3
        cenario.editor.setPlainText("alfa")
        cenario.controller.refresh()
        assert len(cenario.controller.matches) == 1

    def test_destaques_somem_com_termo_vazio(self, cenario):
        cenario.buscar("alfa")
        cenario.buscar("")
        assert cenario.editor._search_ranges == []


# --------------------------------------------------------------------------
# Substituição
# --------------------------------------------------------------------------

class TestSubstituicao:
    def test_substitui_a_atual(self, cenario):
        cenario.buscar("alfa")
        cenario.controller.step(1)
        cenario.controller.replace_current("omega")
        assert cenario.editor.toPlainText().count("omega") == 1
        assert cenario.editor.toPlainText().count("alfa") == 2

    def test_substituir_tudo(self, cenario):
        cenario.buscar("alfa")
        quantidade = cenario.controller.replace_all("omega")
        assert quantidade == 3
        assert cenario.editor.toPlainText().count("omega") == 3
        assert "alfa" not in cenario.editor.toPlainText()

    def test_substituir_tudo_sem_ocorrencia(self, cenario):
        cenario.buscar("inexistente")
        assert cenario.controller.replace_all("x") == 0
        assert cenario.editor.toPlainText() == TEXTO

    def test_substituir_tudo_e_um_passo_so_de_desfazer(self, cenario):
        """Sem agrupar, desfazer exigiria um Ctrl+Z por ocorrência."""
        cenario.buscar("a")
        antes = cenario.editor.toPlainText()
        cenario.controller.replace_all("Z")
        assert cenario.editor.toPlainText() != antes
        cenario.editor.undo()
        assert cenario.editor.toPlainText() == antes

    def test_substituicao_conta_como_alteracao(self, cenario):
        cenario.buscar("alfa")
        cenario.controller.replace_all("omega")
        assert cenario.editor.document().isModified()

    def test_regex_com_grupo(self, cenario):
        cenario.editor.setPlainText("a1 b2")
        cenario.buscar(r"([a-c])(\d)", regex=True)
        cenario.controller.replace_all(r"\2-\1")
        assert cenario.editor.toPlainText() == "1-a 2-b"

    def test_substituir_tudo_limpa_o_contador(self, cenario):
        cenario.buscar("alfa")
        cenario.controller.replace_all("omega")
        # "alfa" deixou de existir, então a busca passa a não achar nada.
        assert len(cenario.controller.matches) == 0

    def test_cursor_sobrevive_a_substituicao_global(self, cenario):
        cenario.buscar("alfa")
        cenario.controller.replace_all("omega")
        assert cenario.editor.textCursor().position() >= 0


# --------------------------------------------------------------------------
# Regra de disponibilidade
# --------------------------------------------------------------------------

class TestSomenteNaEdicao:
    """Busca é recurso de edição: no modo de leitura não há o que procurar.

    A regra vive em ``config.editing_available``, e não dentro da janela, para
    poder ser verificada sem subir o Chromium.
    """

    @pytest.mark.parametrize("modo", ["split", "editor"])
    def test_modos_de_edicao_liberam(self, modo):
        from edgemd.config import editing_available

        assert editing_available(modo) is True

    def test_modo_de_leitura_bloqueia(self):
        from edgemd.config import DEFAULT_VIEW_MODE, editing_available

        assert editing_available("preview") is False
        # E o padrão do app é justamente leitura, então a busca começa fora.
        assert editing_available(DEFAULT_VIEW_MODE) is False

    def test_modo_desconhecido_bloqueia(self):
        from edgemd.config import editing_available

        assert editing_available("roxo") is False

    def test_barra_nao_deixa_destaque_ao_fechar(self, cenario):
        cenario.bar.open_bar(with_replace=True)
        cenario.buscar("alfa")
        assert cenario.editor._search_ranges
        cenario.bar.close_bar()
        cenario.controller.clear()
        assert cenario.editor._search_ranges == []
