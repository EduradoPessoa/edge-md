"""Testes dos ícones das ações.

Um ícone pode renderizar "sem erro" e ainda assim sair vazio ou torto — o
``QSvgRenderer`` devolve um pixmap transparente, sem reclamar, quando o SVG tem
algo que ele não entende. Por isso os testes verificam **pixels desenhados**,
e não só a ausência de exceção.
"""

from __future__ import annotations

import re

import pytest

from edgemd import icon_shapes

pytest.importorskip("PyQt6.QtGui")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from edgemd import icons  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def limpar_cache():
    icons.clear_action_cache()
    yield
    icons.clear_action_cache()


def pixels_pintados(pixmap) -> int:
    """Conta pixels com alguma opacidade — é o que prova que algo foi desenhado."""
    if pixmap.isNull():
        return 0
    image = pixmap.toImage()
    pintados = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 8:
                pintados += 1
    return pintados


class TestDefinicoes:
    def test_conjunto_nao_vazio(self):
        assert len(icon_shapes.available()) >= 30

    def test_nomes_unicos_e_ordenados(self):
        nomes = icon_shapes.available()
        assert len(nomes) == len(set(nomes))
        assert list(nomes) == sorted(nomes)

    def test_nomes_em_kebab_case(self):
        for nome in icon_shapes.available():
            assert re.fullmatch(r"[a-z][a-z0-9-]*", nome), f"nome fora do padrão: {nome}"

    def test_corpo_svg_sem_tag_svg(self):
        """O corpo é injetado dentro da tag; uma tag aninhada quebraria o SVG."""
        for nome, corpo in icon_shapes.ICONS.items():
            assert "<svg" not in corpo, f"{nome} contém <svg>"
            assert "</svg>" not in corpo, f"{nome} contém </svg>"

    def test_sem_cor_fixa(self):
        """Cor literal no desenho impediria o tema de tingir o ícone."""
        for nome, corpo in icon_shapes.ICONS.items():
            assert "#" not in corpo, f"{nome} tem cor literal"
            assert "rgb(" not in corpo, f"{nome} tem cor literal"

    def test_usa_currentcolor_apenas_onde_faz_sentido(self):
        """``fill="currentColor"`` só nos marcadores cheios."""
        for nome, corpo in icon_shapes.ICONS.items():
            if "currentColor" in corpo:
                assert 'fill="currentColor"' in corpo, f"{nome} usa currentColor sem fill"


class TestMarkup:
    def test_injeta_cor_e_tamanho(self):
        markup = icon_shapes.svg_markup('<path d="M4 4h16"/>', "#ff0000", size=32)
        assert 'stroke="#ff0000"' in markup
        assert 'color="#ff0000"' in markup
        assert 'width="32"' in markup
        assert 'height="32"' in markup

    def test_declara_namespace(self):
        # Sem xmlns o QSvgRenderer recusa o documento.
        assert 'xmlns="http://www.w3.org/2000/svg"' in icon_shapes.svg_markup("", "#000")


class TestRenderizacao:
    @pytest.mark.parametrize("nome", icon_shapes.available())
    def test_todo_icone_desenha_alguma_coisa(self, qapp, nome):
        """O teste que importa: se o SVG estiver malformado para o Qt, o pixmap
        sai vazio e ninguém percebe até o botão aparecer em branco."""
        pixmap = icons._render_action(nome, "#e4e7ee", 24)
        assert not pixmap.isNull(), f"{nome} não renderizou"
        assert pixels_pintados(pixmap) > 20, f"{nome} saiu praticamente vazio"

    @pytest.mark.parametrize("nome", icon_shapes.available())
    def test_legivel_em_16px(self, qapp, nome):
        """16 px é o tamanho da barra de ferramentas em telas sem escala."""
        pixmap = icons._render_action(nome, "#e4e7ee", 16)
        assert pixels_pintados(pixmap) > 8, f"{nome} some em 16 px"

    def test_icone_desconhecido_nao_explode(self, qapp):
        pixmap = icons._render_action("nao-existe", "#ffffff", 24)
        assert pixmap.isNull()

    def test_respeita_a_cor_pedida(self, qapp):
        pixmap = icons._render_action("save", "#ff0000", 32)
        image = pixmap.toImage()
        encontrado = False
        for y in range(image.height()):
            for x in range(image.width()):
                cor = image.pixelColor(x, y)
                if cor.alpha() > 200 and cor.red() > 180 and cor.green() < 90:
                    encontrado = True
                    break
            if encontrado:
                break
        assert encontrado, "o ícone não saiu na cor pedida"


class TestCache:
    def test_mesma_cor_reaproveita(self, qapp):
        primeiro = icons.action_icon("save", "#ffffff")
        segundo = icons.action_icon("save", "#ffffff")
        assert primeiro is segundo

    def test_cores_diferentes_geram_icones_diferentes(self, qapp):
        escuro = icons.action_icon("save", "#ffffff")
        claro = icons.action_icon("save", "#000000")
        assert escuro is not claro

    def test_limpar_cache_gera_novos(self, qapp):
        primeiro = icons.action_icon("save", "#ffffff")
        icons.clear_action_cache()
        segundo = icons.action_icon("save", "#ffffff")
        assert primeiro is not segundo

    def test_icone_tem_varios_tamanhos(self, qapp):
        """O Qt escolhe o tamanho conforme o contexto e a escala da tela.

        ``availableSizes()`` reporta o tamanho de *device*: os pixmaps são
        renderizados com fator 2 para sair nítidos em telas HiDPI, então um
        ícone lógico de 16 px aparece lá como 32. O que importa é que pedir um
        tamanho lógico devolva o tamanho lógico certo.
        """
        icone = icons.action_icon("save", "#ffffff")
        assert len(icone.availableSizes()) >= 3

        for alvo in (16, 24, 32):
            pixmap = icone.pixmap(alvo, alvo)
            assert not pixmap.isNull()
            logico = pixmap.width() / pixmap.devicePixelRatio()
            assert abs(logico - alvo) < 1.5, f"pedi {alvo} e recebi {logico}"


class TestCoberturaDasAcoes:
    def test_toda_acao_com_icone_existe(self):
        """Nomes pedidos pela janela precisam existir no conjunto desenhado.

        Um nome errado ou esquecido daria um botão invisível na barra — falha
        que passa fácil numa revisão de código, porque o app não reclama.
        """
        faltando = [nome for nome in icon_shapes.USED_ACTIONS if nome not in icon_shapes.ICONS]
        assert faltando == [], f"ícones pedidos e não desenhados: {faltando}"

    def test_lista_de_uso_nao_tem_repetidos(self):
        assert len(icon_shapes.USED_ACTIONS) == len(set(icon_shapes.USED_ACTIONS))

    def test_ha_icones_desenhados_alem_dos_usados(self):
        """O conjunto desenhado pode ser maior — sobra para uso futuro."""
        assert set(icon_shapes.USED_ACTIONS).issubset(icon_shapes.ICONS)
