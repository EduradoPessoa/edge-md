"""Testes do catálogo de emojis e do seletor."""

from __future__ import annotations

import pytest

from edgemd import emojis

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from edgemd.emoji_picker import COLUNAS, LIMITE_BUSCA, EmojiPicker  # noqa: E402


class TestCatalogo:
    def test_tem_um_bom_numero(self):
        assert len(emojis.all_emojis()) > 300

    def test_categorias_nao_vazias(self):
        for nome in emojis.categories():
            assert emojis.by_category(nome), f"categoria vazia: {nome}"

    def test_sem_emoji_repetido(self):
        """O mesmo emoji em duas categorias apareceria duas vezes na grade."""
        chars = [e.char for e in emojis.all_emojis()]
        repetidos = {c for c in chars if chars.count(c) > 1}
        assert repetidos == set()

    def test_todo_emoji_tem_nome(self):
        for emoji in emojis.all_emojis():
            assert emoji.name.strip(), f"emoji sem nome: {emoji.char!r}"

    def test_nomes_unicos_dentro_da_categoria(self):
        for nome in emojis.categories():
            rotulos = [e.name for e in emojis.by_category(nome)]
            assert len(rotulos) == len(set(rotulos)), f"nomes repetidos em {nome}"

    def test_categoria_inexistente_devolve_vazio(self):
        assert emojis.by_category("Inexistente") == ()


class TestBusca:
    def test_termo_vazio_devolve_tudo(self):
        assert len(emojis.search("")) == len(emojis.all_emojis())

    def test_acha_por_nome(self):
        assert "😀" in {e.char for e in emojis.search("sorriso aberto")}

    def test_ignora_caixa(self):
        assert emojis.search("FELIZ") == emojis.search("feliz")

    def test_ignora_acento(self):
        """Quem digita 'coracao' precisa achar 'Coração'."""
        assert "❤️" in {e.char for e in emojis.search("coracao")}

    def test_acha_por_palavra_chave(self):
        assert "🔥" in {e.char for e in emojis.search("quente")}

    def test_acha_por_apelido_do_github(self):
        assert [e.char for e in emojis.search("tada")] == ["🎉"]

    def test_apelido_com_dois_pontos(self):
        assert [e.char for e in emojis.search(":rocket:")] == ["🚀"]

    def test_apelido_tem_prioridade(self):
        """'book' deve trazer o livro, não tudo que contenha 'book'."""
        resultado = emojis.search("book")
        assert resultado and resultado[0].char == "📚"

    def test_termo_sem_resultado(self):
        assert emojis.search("zzzznaoexiste") == ()

    def test_limite(self):
        assert len(emojis.search("a", limit=10)) == 10

    def test_sem_limite_devolve_tudo(self):
        assert len(emojis.search("a")) == len(
            [e for e in emojis.all_emojis() if "a" in e.haystack()]
        )

    def test_busca_nao_depende_da_categoria(self):
        """Quem digita 'bug' não sabe em qual categoria o emoji mora."""
        de_categorias_diferentes = {e.char for e in emojis.search("bug")}
        assert de_categorias_diferentes


class TestApelidos:
    def test_todos_apontam_para_emoji_existente(self):
        existentes = {e.char for e in emojis.all_emojis()}
        orfaos = {a: c for a, c in emojis.ALIASES.items() if c not in existentes}
        assert orfaos == {}, f"apelidos sem emoji no catálogo: {orfaos}"

    def test_chaves_normalizadas(self):
        """Apelido com maiúscula nunca casaria, já que a busca normaliza."""
        for apelido in emojis.ALIASES:
            assert apelido == emojis.normalize(apelido)


class TestNormalize:
    def test_remove_acento_e_caixa(self):
        assert emojis.normalize("Coração") == "coracao"

    def test_texto_simples(self):
        assert emojis.normalize("Bug") == "bug"


@pytest.fixture
def picker(qapp):
    widget = EmojiPicker()
    yield widget
    widget.deleteLater()


class TestSeletor:
    def test_comeca_com_tudo(self, picker):
        assert picker.count() == len(emojis.all_emojis())

    def test_tem_botao_para_cada_categoria(self, picker):
        assert len(picker._category_buttons) == len(emojis.categories()) + 1

    def test_filtra_por_categoria(self, picker):
        picker._set_category("Comida")
        assert picker.count() == len(emojis.by_category("Comida"))

    def test_volta_para_todos(self, picker):
        picker._set_category("Comida")
        picker._set_category(None)
        assert picker.count() == len(emojis.all_emojis())

    def test_busca_filtra_a_grade(self, picker):
        picker.search_input.setText("foguete")
        assert picker.count() == 1

    def test_busca_vazia_restaura(self, picker):
        picker.search_input.setText("foguete")
        picker.search_input.setText("")
        assert picker.count() == len(emojis.all_emojis())

    def test_busca_respeita_o_limite(self, picker):
        picker.search_input.setText("a")
        assert picker.count() <= LIMITE_BUSCA

    def test_busca_sem_resultado_mostra_o_aviso(self, picker):
        picker.search_input.setText("zzzznaoexiste")
        assert picker.count() == 0
        assert picker._empty_label.isVisible() or not picker._empty_label.isHidden()

    def test_escolher_emite_o_caractere(self, picker):
        escolhidos: list[str] = []
        picker.emojiChosen.connect(escolhidos.append)

        picker.search_input.setText("foguete")
        botao = picker._grid.itemAt(0).widget()
        botao.click()

        assert escolhidos == ["🚀"]

    def test_enter_escolhe_o_primeiro(self, picker):
        escolhidos: list[str] = []
        picker.emojiChosen.connect(escolhidos.append)

        picker.search_input.setText("foguete")
        picker.search_input.returnPressed.emit()

        assert escolhidos == ["🚀"]

    def test_enter_sem_resultado_nao_emite(self, picker):
        escolhidos: list[str] = []
        picker.emojiChosen.connect(escolhidos.append)

        picker.search_input.setText("zzzznaoexiste")
        picker.search_input.returnPressed.emit()

        assert escolhidos == []

    def test_grade_usa_varias_colunas(self, picker):
        assert COLUNAS > 1
        assert picker._grid.columnCount() <= COLUNAS

    def test_nao_acumula_botoes_ao_trocar_de_categoria(self, picker):
        """Trocar de categoria precisa limpar a grade, não empilhar."""
        picker._set_category("Comida")
        picker._set_category("Animais")
        assert picker.count() == len(emojis.by_category("Animais"))
