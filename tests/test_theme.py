"""Testes do tema unificado.

A regra que estes testes protegem: **uma paleta, duas saídas**. Antes, o
preview tinha cores próprias em CSS e o Qt usava o visual nativo — trocar o
tema mudava só o documento e deixava menus e barras claros. Se alguém voltar a
declarar cor nos dois lugares, o teste de sincronia abaixo quebra.
"""

from __future__ import annotations

import re

import pytest

from edgemd.paths import asset_path
from edgemd.theme import (
    DARK,
    DEFAULT_THEME,
    LIGHT,
    PALETTES,
    THEMES,
    apply_app_theme,
    colors,
    qt_stylesheet,
    web_css,
)

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# --------------------------------------------------------------------------
# Paleta
# --------------------------------------------------------------------------

class TestPaleta:
    @pytest.mark.parametrize("tema", THEMES)
    def test_tema_completo(self, tema):
        """Nenhum campo pode ficar vazio — a cor some e o widget fica ilegível."""
        dados = colors(tema).__dict__
        vazios = [k for k, v in dados.items() if v in (None, "")]
        assert vazios == [], f"tema {tema} com campos vazios: {vazios}"

    @pytest.mark.parametrize("tema", THEMES)
    def test_cores_da_paleta_sao_validas(self, tema):
        """Hex é validado pelo ``QColor``; ``rgba()`` só existe para o CSS.

        O ``QColor`` não entende a sintaxe CSS ``rgba()`` — ele a rejeita. Como
        esses valores são consumidos apenas pelo Chromium, a validação deles é
        pela forma, e não pelo Qt.
        """
        from PyQt6.QtGui import QColor

        for campo, valor in colors(tema).__dict__.items():
            if not isinstance(valor, str) or not valor.startswith(("#", "rgba")):
                continue  # medidas, fontes, sombras

            if valor.startswith("#"):
                assert re.fullmatch(r"#[0-9a-fA-F]{6}", valor), f"{tema}.{campo} = {valor!r}"
                assert QColor(valor).isValid(), f"{tema}.{campo} = {valor!r}"
            else:
                assert re.fullmatch(
                    r"rgba\(\s*\d{1,3},\s*\d{1,3},\s*\d{1,3},\s*(?:0?\.\d+|[01])\s*\)",
                    valor,
                ), f"{tema}.{campo} = {valor!r} não é um rgba() CSS válido"

    @pytest.mark.parametrize("tema", THEMES)
    def test_qss_nao_usa_rgba_com_alfa_fracionario(self, tema):
        """O QSS do Qt não aceita alfa decimal como o CSS aceita.

        No Qt a forma segura é ``rgba(r, g, b, 25%)`` ou alfa inteiro de 0 a
        255. Um ``rgba(..., 0.2)`` vindo do CSS seria descartado em silêncio, e
        a regra sumiria sem aviso.
        """
        qss = qt_stylesheet(tema)
        for encontrado in re.findall(r"rgba\([^)]*\)", qss):
            alfa = encontrado.rsplit(",", 1)[-1].strip().rstrip(")")
            assert "%" in alfa or "." not in alfa, (
                f"alfa fracionário no QSS do tema {tema}: {encontrado}"
            )

    def test_tema_desconhecido_cai_para_o_padrao(self):
        assert colors("roxo") is PALETTES[DEFAULT_THEME]

    def test_contraste_de_texto_sobre_fundo(self):
        """Texto e fundo não podem ser próximos, senão a interface some."""
        from PyQt6.QtGui import QColor

        def luminancia(valor: str) -> float:
            cor = QColor(valor)
            return (0.2126 * cor.red() + 0.7152 * cor.green() + 0.0722 * cor.blue()) / 255

        for tema, paleta in PALETTES.items():
            fundo = luminancia(paleta.bg)
            texto = luminancia(paleta.fg)
            assert abs(fundo - texto) > 0.5, (
                f"tema {tema}: contraste insuficiente entre fundo e texto"
            )


class TestSincroniaComOCss:
    """O CSS do preview e o QSS do Qt têm de sair da mesma paleta."""

    @pytest.mark.parametrize("tema", THEMES)
    def test_css_em_disco_bate_com_a_paleta(self, tema):
        """Se falhar, rode: python tools/generate_theme_css.py

        O CSS fica em disco porque quem o lê é o Chromium, não o Python. Este
        teste é o que impede que ele envelheça em relação à paleta.
        """
        caminho = asset_path(f"theme-{tema}.css")
        assert caminho.is_file(), f"theme-{tema}.css não existe"

        conteudo = caminho.read_text(encoding="utf-8")
        variaveis = dict(re.findall(r"--([\w-]+):\s*([^;]+);", conteudo))

        esperado = colors(tema).css_variables()
        for chave, valor in esperado.items():
            assert chave in variaveis, f"--{chave} sumiu de theme-{tema}.css"
            assert variaveis[chave].strip() == valor, (
                f"--{chave} divergiu em theme-{tema}.css: "
                f"arquivo={variaveis[chave]!r}, paleta={valor!r}"
            )

    @pytest.mark.parametrize("tema", THEMES)
    def test_todas_as_variaveis_esperadas_presentes(self, tema):
        variaveis = colors(tema).css_variables()
        # Estas são consumidas por base.css e não podem desaparecer.
        for obrigatoria in ("bg", "fg", "accent", "border", "code-bg", "font-mono"):
            assert obrigatoria in variaveis

    @pytest.mark.parametrize("tema", THEMES)
    def test_web_css_declara_cada_variavel_uma_vez(self, tema):
        css = web_css(tema)
        for chave in colors(tema).css_variables():
            assert css.count(f"--{chave}:") == 1, f"--{chave} duplicada ou ausente"

    def test_web_css_marca_o_color_scheme(self):
        # O Chromium usa isto para escolher o visual de barras de rolagem e
        # controles nativos do documento.
        assert "color-scheme: dark" in web_css("dark")
        assert "color-scheme: light" in web_css("light")


class TestQss:
    @pytest.mark.parametrize("tema", THEMES)
    def test_cobre_os_widgets_principais(self, tema):
        """Cada peça da interface precisa de regra, senão fica no visual nativo."""
        qss = qt_stylesheet(tema)
        for seletor in (
            "QMenuBar", "QMenu", "QToolBar", "QToolButton", "QTabBar::tab",
            "QTreeView", "QLineEdit", "QPushButton", "QStatusBar",
            "QSplitter::handle", "QScrollBar:vertical", "QToolTip",
            "QWidget#modeBar", "QPushButton#modeBarButton",
        ):
            assert seletor in qss, f"{seletor} sem estilo no tema {tema}"

    @pytest.mark.parametrize("tema", THEMES)
    def test_usa_cores_da_paleta(self, tema):
        qss = qt_stylesheet(tema)
        paleta = colors(tema)
        # Uma amostra: se o QSS tivesse cores próprias, estes valores não
        # apareceriam nele.
        for valor in (paleta.bg, paleta.bg_elev, paleta.fg, paleta.accent):
            assert valor in qss, f"{valor} não aparece no QSS do tema {tema}"

    @pytest.mark.parametrize("tema", THEMES)
    def test_chaves_balanceadas(self, tema):
        """QSS malformado faz o Qt descartar a folha inteira em silêncio."""
        qss = qt_stylesheet(tema)
        assert qss.count("{") == qss.count("}")

    def test_temas_diferentes_geram_qss_diferentes(self):
        assert qt_stylesheet("dark") != qt_stylesheet("light")


class TestAplicacao:
    def test_aplica_e_devolve_o_tema(self, qapp):
        assert apply_app_theme(qapp, "dark") == "dark"
        assert apply_app_theme(qapp, "light") == "light"

    def test_tema_invalido_cai_para_o_padrao(self, qapp):
        assert apply_app_theme(qapp, "roxo") == DEFAULT_THEME

    def test_nao_usa_o_estilo_nativo_do_windows(self, qapp):
        """O estilo nativo ignora boa parte do QSS.

        Sem trocar para Fusion, menus e barra de ferramentas continuariam
        claros num tema escuro — o defeito relatado. Depois de aplicar a folha,
        o Qt embrulha o estilo num ``QStyleSheetStyle``, então não dá para
        procurar por "Fusion" diretamente: o que importa é *não* estar no
        estilo nativo.
        """
        apply_app_theme(qapp, "dark")
        classe = qapp.style().metaObject().className()
        assert classe in ("QFusionStyle", "QStyleSheetStyle"), classe
        assert "Windows" not in classe, f"ainda no estilo nativo: {classe}"

    def test_troca_efetiva_o_stylesheet(self, qapp):
        apply_app_theme(qapp, "dark")
        escuro = qapp.styleSheet()
        apply_app_theme(qapp, "light")
        claro = qapp.styleSheet()
        assert escuro and claro
        assert escuro != claro
        assert DARK.bg in escuro
        assert LIGHT.bg in claro

    def test_paleta_do_qt_tambem_e_trocada(self, qapp):
        """O QSS não alcança tudo; a QPalette cobre o resto."""
        from PyQt6.QtGui import QColor, QPalette

        apply_app_theme(qapp, "dark")
        escuro = qapp.palette().color(QPalette.ColorRole.Window)
        apply_app_theme(qapp, "light")
        claro = qapp.palette().color(QPalette.ColorRole.Window)
        assert escuro != claro
        assert claro == QColor(LIGHT.bg)
