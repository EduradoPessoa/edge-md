"""Testes da lógica de busca e substituição.

O foco é nos detalhes que erram em silêncio: escape de metacaractere, palavra
inteira, maiúsculas, ocorrência de comprimento zero (que trava a busca) e a
referência ``\\1`` na substituição por expressão regular.
"""

from __future__ import annotations

import pytest

from edgemd.search import (
    Match,
    SearchOptions,
    build_pattern,
    count_occurrences,
    find_all,
    index_of_match_at,
    pattern_error,
    replace_all_in_text,
)

TEXTO = "O rato roeu a roupa do rei de Roma.\nO RATO voltou."


class TestPadrao:
    def test_sem_termo(self):
        assert build_pattern("", SearchOptions()) is None

    def test_escapa_metacaractere_por_padrao(self):
        """Procurar 'a.b' não pode casar 'axb'."""
        assert len(find_all("a.b axb", "a.b", SearchOptions())) == 1

    def test_regex_liga_metacaractere(self):
        assert len(find_all("a.b axb", "a.b", SearchOptions(regex=True))) == 2

    def test_insensivel_por_padrao(self):
        assert len(find_all("Casa casa CASA", "casa", SearchOptions())) == 3

    def test_sensivel_a_caixa(self):
        opcoes = SearchOptions(case_sensitive=True)
        assert len(find_all("Casa casa CASA", "casa", opcoes)) == 1

    def test_palavra_inteira(self):
        assert len(find_all("rato ratoeira", "rato", SearchOptions(whole_word=True))) == 1
        assert len(find_all("rato ratoeira", "rato", SearchOptions())) == 2

    def test_palavra_inteira_com_acento(self):
        opcoes = SearchOptions(whole_word=True)
        assert len(find_all("ação açãozinha", "ação", opcoes)) == 1

    def test_regex_escapada_com_palavra_inteira(self):
        """A ordem importa: escapar antes de envolver em \\b."""
        opcoes = SearchOptions(whole_word=True, regex=False)
        assert len(find_all("a.b axb", "a.b", opcoes)) == 1

    def test_descricao_das_opcoes(self):
        assert SearchOptions().describe() == "busca simples"
        descricao = SearchOptions(case_sensitive=True, whole_word=True).describe()
        assert "maiúsculas" in descricao
        assert "palavra inteira" in descricao


class TestErroDePadrao:
    def test_regex_invalida(self):
        erro = pattern_error("([", SearchOptions(regex=True))
        assert erro
        assert "]" in erro

    def test_regex_valida(self):
        assert pattern_error(r"\d+", SearchOptions(regex=True)) is None

    def test_erro_so_existe_em_modo_regex(self):
        # Fora do modo regex o termo é escapado, então nunca é inválido.
        assert pattern_error("([", SearchOptions()) is None

    def test_termo_vazio(self):
        assert pattern_error("", SearchOptions(regex=True)) is None


class TestBusca:
    def test_posicoes(self):
        encontradas = find_all("abc abc", "abc", SearchOptions())
        assert [(m.start, m.length) for m in encontradas] == [(0, 3), (4, 3)]

    def test_match_expõe_o_fim(self):
        match = Match(10, 5)
        assert match.end == 15

    def test_ocorrencia_vazia_e_descartada(self):
        """Sem isso a navegação entraria em laço: a posição nunca avançaria."""
        assert find_all("bbb", "a*", SearchOptions(regex=True)) == ()

    def test_termo_ausente(self):
        assert find_all("nada aqui", "zzz", SearchOptions()) == ()

    def test_contagem_bate_com_a_lista(self):
        assert count_occurrences(TEXTO, "rato", SearchOptions()) == len(
            find_all(TEXTO, "rato", SearchOptions())
        )

    def test_ordena_por_posicao(self):
        encontradas = find_all(TEXTO, "Roma", SearchOptions())
        assert all(
            encontradas[i].start < encontradas[i + 1].start
            for i in range(len(encontradas) - 1)
        )

    def test_nao_cruza_linha_sem_flag(self):
        # "." não casa quebra de linha por padrão no Qt.
        assert len(find_all("a\nb", "a.b", SearchOptions(regex=True))) == 0


class TestSubstituicao:
    def test_troca_todas(self):
        novo, quantidade = replace_all_in_text(
            TEXTO, "rato", "gato", SearchOptions()
        )
        assert quantidade == 2
        assert "gato" in novo
        assert "rato" not in novo.lower()

    def test_sem_ocorrencia_nao_altera(self):
        novo, quantidade = replace_all_in_text("abc", "zzz", "x", SearchOptions())
        assert quantidade == 0
        assert novo == "abc"

    def test_termo_vazio(self):
        novo, quantidade = replace_all_in_text("abc", "", "x", SearchOptions())
        assert quantidade == 0
        assert novo == "abc"

    def test_preserva_maiusculas_do_original(self):
        """A troca é literal: não tenta adivinhar a caixa."""
        novo, _ = replace_all_in_text(TEXTO, "RATO", "gato", SearchOptions())
        assert "gato voltou" in novo

    def test_referencia_de_grupo(self):
        novo, quantidade = replace_all_in_text(
            "a1 b2 c3", r"([a-c])(\d)", r"\2-\1", SearchOptions(regex=True)
        )
        assert quantidade == 3
        assert novo == "1-a 2-b 3-c"

    def test_referencia_inexistente_vira_vazio(self):
        novo, _ = replace_all_in_text(
            "abc", r"(a)", r"[\5]", SearchOptions(regex=True)
        )
        assert novo == "[]bc"

    def test_barra_escapada_vira_barra_simples(self):
        """``\\\\`` no texto de substituição produz uma barra só."""
        novo, _ = replace_all_in_text("a", r"(a)", r"\\", SearchOptions(regex=True))
        assert novo == "\\"

    def test_caminho_nao_e_interpretado_como_referencia(self):
        """Trocar por um caminho não pode consumir a barra invertida.

        Só ``\\`` seguido de dígito é referência de grupo; ``\\n`` é texto.
        """
        novo, _ = replace_all_in_text(
            "origem", "(origem)", r"C:\nova", SearchOptions(regex=True)
        )
        assert novo == r"C:\nova"

    def test_palavra_inteira_na_substituicao(self):
        novo, quantidade = replace_all_in_text(
            "rato ratoeira", "rato", "gato", SearchOptions(whole_word=True)
        )
        assert quantidade == 1
        assert novo == "gato ratoeira"

    def test_preserva_o_resto_do_texto(self):
        original = "antes MEIO depois"
        novo, _ = replace_all_in_text(original, "MEIO", "X", SearchOptions())
        assert novo == "antes X depois"

    def test_multiplas_linhas(self):
        novo, quantidade = replace_all_in_text(
            "a\nb\na\n", "a", "X", SearchOptions()
        )
        assert quantidade == 2
        assert novo == "X\nb\nX\n"


class TestIndiceDaOcorrencia:
    def test_encontra_a_que_contem(self):
        encontradas = (Match(0, 3), Match(10, 4))
        assert index_of_match_at(encontradas, 1) == 0
        assert index_of_match_at(encontradas, 11) == 1

    def test_fora_de_qualquer_uma(self):
        encontradas = (Match(0, 3), Match(10, 4))
        assert index_of_match_at(encontradas, 6) == -1

    def test_lista_vazia(self):
        assert index_of_match_at((), 0) == -1

    def test_limite_inferior_inclusivo(self):
        assert index_of_match_at((Match(5, 3),), 5) == 0

    def test_limite_superior_exclusivo(self):
        # O fim de uma ocorrência é o começo da seguinte, não dela mesma.
        assert index_of_match_at((Match(5, 3),), 8) == -1


@pytest.mark.parametrize(
    "termo,opcoes,esperado",
    [
        ("rato", SearchOptions(), 2),
        ("rato", SearchOptions(case_sensitive=True), 1),
        ("RATO", SearchOptions(case_sensitive=True), 1),
        ("rato", SearchOptions(whole_word=True), 2),
        # r\w+ casa rato, roeu, roupa, rei, Roma e RATO.
        (r"r\w+", SearchOptions(regex=True), 6),
        # Com palavra inteira, "rat" não casa — mas "rato" sim, duas vezes.
        ("rat", SearchOptions(whole_word=True), 0),
        ("ausente", SearchOptions(), 0),
    ],
)
def test_contagens_no_texto_de_referencia(termo, opcoes, esperado):
    assert count_occurrences(TEXTO, termo, opcoes) == esperado
