"""Lógica de busca no texto do editor.

Separado da interface de propósito: encontrar ocorrências é aritmética sobre
strings, e é a parte que mais erra em detalhe (escape de regex, palavra
inteira, maiúsculas). Aqui dá para testar sem abrir janela nenhuma; a barra
visual apenas consome o resultado.

Usa ``QRegularExpression`` em vez do módulo ``re`` para que o padrão seja
exatamente o mesmo que o ``QTextDocument`` usa ao localizar — misturar os dois
motores daria contagens diferentes das encontradas na hora de substituir.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PyQt6.QtCore import QRegularExpression

#: Limite de ocorrências destacadas de uma vez.
#:
#: Buscar "a" num arquivo grande casaria dezenas de milhares de vezes, e cada
#: ocorrência vira uma seleção extra que o Qt repinta. O contador continua
#: mostrando o total real; só o destaque é limitado.
MAX_HIGHLIGHTS = 5000


@dataclass(frozen=True)
class SearchOptions:
    """Como interpretar o termo buscado."""

    case_sensitive: bool = False
    whole_word: bool = False
    regex: bool = False

    def describe(self) -> str:
        """Descrição curta, usada em dica de tela e mensagem."""
        partes = []
        if self.case_sensitive:
            partes.append("maiúsculas e minúsculas")
        if self.whole_word:
            partes.append("palavra inteira")
        if self.regex:
            partes.append("expressão regular")
        return ", ".join(partes) if partes else "busca simples"


@dataclass(frozen=True)
class Match:
    """Uma ocorrência: posição inicial e comprimento, em caracteres."""

    start: int
    length: int

    @property
    def end(self) -> int:
        return self.start + self.length


#: Sentinela para "nenhum resultado", evitando repetir a construção.
NO_MATCHES: tuple[Match, ...] = ()


def build_pattern(query: str, options: SearchOptions) -> QRegularExpression | None:
    """Compila o padrão de busca, ou None se não houver o que buscar.

    Com ``regex`` desligado o termo é escapado: sem isso, procurar por
    ``a.b`` casaria ``axb``, e o usuário veria resultados que não pediu. Com
    ``whole_word``, o termo é envolvido por ``\\b``.
    """
    if not query:
        return None

    body = query if options.regex else QRegularExpression.escape(query)
    if options.whole_word:
        body = rf"\b(?:{body})\b"

    pattern = QRegularExpression(body)
    if options.case_sensitive:
        pattern.setPatternOptions(QRegularExpression.PatternOption.NoPatternOption)
    else:
        pattern.setPatternOptions(
            QRegularExpression.PatternOption.CaseInsensitiveOption
        )

    return pattern if pattern.isValid() else None


def pattern_error(query: str, options: SearchOptions) -> str | None:
    """Mensagem de erro do padrão, ou None quando ele é válido.

    Serve para avisar sobre uma regex malformada enquanto o usuário digita, em
    vez de simplesmente não encontrar nada.
    """
    if not query or not options.regex:
        return None

    pattern = QRegularExpression(query)
    if pattern.isValid():
        return None

    return pattern.errorString() or "expressão regular inválida"


def find_all(
    text: str, query: str, options: SearchOptions
) -> tuple[Match, ...]:
    """Todas as ocorrências de ``query`` em ``text``, em ordem.

    Ocorrências de comprimento zero (possíveis em regex, como ``a*``) são
    descartadas: não há o que destacar nem o que substituir, e elas fariam o
    avanço da busca entrar em laço infinito.
    """
    pattern = build_pattern(query, options)
    if pattern is None:
        return NO_MATCHES

    encontradas: list[Match] = []
    iterator = pattern.globalMatch(text)
    while iterator.hasNext():
        match = iterator.next()
        tamanho = match.capturedLength()
        if tamanho > 0:
            encontradas.append(Match(match.capturedStart(), tamanho))

    return tuple(encontradas)


def count_occurrences(text: str, query: str, options: SearchOptions) -> int:
    """Quantas ocorrências existem, sem materializar a lista."""
    return len(find_all(text, query, options))


def _expand_backreferences(template: str, match) -> str:
    """Resolve ``\\1``..``\\9`` e ``\\\\`` no texto de substituição.

    O PyQt6 não expõe o ``globalSubstitute`` do Qt, então a expansão é feita
    aqui. Só ``\\`` seguido de dígito é tratado como referência: assim um
    caminho como ``C:\\Users`` continua sendo escrito literalmente, sem
    precisar escapar barra.
    """
    saida: list[str] = []
    i = 0
    total = len(template)

    while i < total:
        caractere = template[i]
        if caractere == "\\" and i + 1 < total:
            seguinte = template[i + 1]
            if seguinte.isdigit():
                indice = int(seguinte)
                if indice <= match.lastCapturedIndex():
                    saida.append(match.captured(indice))
                i += 2
                continue
            if seguinte == "\\":
                saida.append("\\")
                i += 2
                continue
        saida.append(caractere)
        i += 1

    return "".join(saida)


def replace_all_in_text(
    text: str, query: str, replacement: str, options: SearchOptions
) -> tuple[str, int]:
    """Devolve ``(texto_novo, quantidade)`` com todas as ocorrências trocadas.

    Percorre as ocorrências e remonta a string, em vez de substituir uma a uma
    pelo cursor: assim a operação é atômica e entra no histórico de desfazer
    como um passo único, em vez de N passos.
    """
    pattern = build_pattern(query, options)
    if pattern is None:
        return text, 0

    partes: list[str] = []
    ultimo = 0
    quantidade = 0

    iterator = pattern.globalMatch(text)
    while iterator.hasNext():
        match = iterator.next()
        # Ocorrência vazia não tem o que trocar e não avança a posição.
        if match.capturedLength() == 0:
            continue

        partes.append(text[ultimo:match.capturedStart()])
        partes.append(
            _expand_backreferences(replacement, match)
            if options.regex
            else replacement
        )
        ultimo = match.capturedEnd()
        quantidade += 1

    if quantidade == 0:
        return text, 0

    partes.append(text[ultimo:])
    return "".join(partes), quantidade


def index_of_match_at(matches: Iterable[Match], position: int) -> int:
    """Índice da ocorrência que contém ``position``, ou -1.

    Usado depois de o usuário substituir: o cursor está sobre a ocorrência que
    acabou de mudar de tamanho, e a lista de destaques precisa refazer as
    contas.
    """
    for indice, match in enumerate(matches):
        if match.start <= position < match.end:
            return indice
    return -1
