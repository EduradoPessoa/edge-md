"""Testes do modo de leitura e da faixa que entra na edição.

A regra que estes testes protegem: o app abre **lendo**. Editar é a exceção,
alcançada por um clique num componente visível — e não pelo estado deixado na
sessão anterior.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from edgemd.mode_bar import ModeBar  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def bar(qapp):
    widget = ModeBar()
    yield widget
    widget.deleteLater()


class TestModoPadrao:
    def test_app_abre_lendo(self):
        """O modo inicial é leitura: o app é um leitor de Markdown."""
        # Vem de config, e nao de window: importar a janela subiria o
        # Chromium so para ler uma constante.
        from edgemd.config import DEFAULT_VIEW_MODE

        assert DEFAULT_VIEW_MODE == "preview"

    def test_config_nao_guarda_o_modo(self):
        """O modo não é persistido.

        Se fosse, um .md aberto no dia seguinte começaria em edição por causa
        da sessão anterior — exatamente o que o padrão de leitura evita.
        """
        from edgemd.config import AppConfig

        import inspect

        fonte = inspect.getsource(AppConfig)
        assert "view_mode" not in fonte


class TestFaixaDeModo:
    def test_rotulo_em_leitura(self, bar):
        bar.set_mode("preview")
        assert bar._button.text() == "Editar"

    @pytest.mark.parametrize("modo", ["split", "editor"])
    def test_rotulo_em_edicao(self, bar, modo):
        bar.set_mode(modo)
        assert bar._button.text() == "Concluir"

    def test_clique_em_leitura_pede_edicao(self, bar):
        bar.set_mode("preview")
        chamadas: list[str] = []
        bar.editRequested.connect(lambda: chamadas.append("editar"))
        bar.readRequested.connect(lambda: chamadas.append("ler"))

        bar._button.click()
        assert chamadas == ["editar"]

    @pytest.mark.parametrize("modo", ["split", "editor"])
    def test_clique_em_edicao_volta_a_ler(self, bar, modo):
        bar.set_mode(modo)
        chamadas: list[str] = []
        bar.editRequested.connect(lambda: chamadas.append("editar"))
        bar.readRequested.connect(lambda: chamadas.append("ler"))

        bar._button.click()
        assert chamadas == ["ler"]

    def test_mostra_o_nome_do_documento(self, bar):
        bar.set_document_name(r"C:\notas\receita.md")
        assert "receita.md" in bar._label.text()

    def test_marca_alteracao_nao_salva(self, bar):
        bar.set_document_name("receita.md", dirty=False)
        limpo = bar._label.text()
        bar.set_document_name("receita.md", dirty=True)
        assert bar._label.text() != limpo
        assert "•" in bar._label.text()

    def test_sem_documento(self, bar):
        bar.set_document_name("Nenhum arquivo aberto")
        assert "Nenhum" in bar._label.text()


class TestEstilo:
    """A faixa não carrega folha de estilo própria.

    Ela é vestida pelo QSS global, por ``objectName``. Se este contrato quebrar
    (um ``objectName`` renomeado, por exemplo), a faixa volta a aparecer no
    visual nativo do Windows dentro de um app de tema escuro — o defeito que
    motivou a existência do ``theme.py``.
    """

    def test_object_names_publicados(self, bar):
        assert bar.objectName() == "modeBar"
        assert bar._label.objectName() == "modeBarLabel"
        assert bar._button.objectName() == "modeBarButton"

    def test_faixa_nao_tem_css_proprio(self, bar):
        assert bar.styleSheet() == ""

    @pytest.mark.parametrize("tema", ["light", "dark"])
    def test_qss_global_cobre_os_object_names(self, tema):
        from edgemd.theme import qt_stylesheet

        qss = qt_stylesheet(tema)
        for selector in ("QWidget#modeBar", "QLabel#modeBarLabel", "QPushButton#modeBarButton"):
            assert selector in qss, f"{selector} sumiu do QSS do tema {tema}"

    @pytest.mark.parametrize("tema", ["light", "dark"])
    def test_botao_contrasta_com_o_fundo(self, tema):
        """O botão é o caminho para a edição; precisa se destacar da faixa."""
        from edgemd.theme import colors

        palette = colors(tema)
        assert palette.button_bg != palette.bg_elev, tema
        assert palette.button_fg != palette.button_bg, tema
