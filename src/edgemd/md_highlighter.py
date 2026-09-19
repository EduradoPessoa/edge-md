"""Realce de sintaxe Markdown para o editor.

Usa ``QSyntaxHighlighter``, que o Qt chama apenas para os blocos que mudaram —
por isso digitar num arquivo grande não re-realiza o documento inteiro.

Blocos de código com cerca (````` ``` `````) atravessam várias linhas, então são
tratados por máquina de estado via ``previousBlockState()``, e não por regex de
linha. Sem isso, uma cerca nunca fecharia visualmente.
"""

from __future__ import annotations

import re

from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)

#: Estado gravado em cada bloco: 0 = texto normal, 1 = dentro de bloco de código.
STATE_NORMAL = 0
STATE_FENCED_CODE = 1

#: (chave, cor do texto, cor de fundo opcional, negrito, itálico, sublinhado)
PALETTES: dict[str, dict[str, tuple[str, str | None, bool, bool, bool]]] = {
    "dark": {
        "heading":     ("#7cb0ff", None, True, False, False),
        "bold":        ("#f0f3f9", None, True, False, False),
        "italic":      ("#d6dae3", None, False, True, False),
        "strike":      ("#6f7787", None, False, False, True),
        "code_inline": ("#f2a3a3", "#23272f", False, False, False),
        "fence":       ("#7ee0a8", None, False, False, False),
        "code_body":   ("#c3c9d5", None, False, False, False),
        "link":        ("#6ea8fe", None, False, False, True),
        "url":         ("#8d97a8", None, False, False, False),
        "image":       ("#c9a0ff", None, False, False, False),
        "quote":       ("#9aa3b4", None, False, True, False),
        "list":        ("#e0a33e", None, True, False, False),
        "task_done":   ("#52c98a", None, True, False, False),
        "task_todo":   ("#e0a33e", None, True, False, False),
        "hr":          ("#4a5160", None, False, False, False),
        "table":       ("#7cb0ff", None, False, False, False),
        "html":        ("#8d97a8", None, False, False, False),
    },
    "light": {
        "heading":     ("#0a4fa8", None, True, False, False),
        "bold":        ("#12171d", None, True, False, False),
        "italic":      ("#2b3138", None, False, True, False),
        "strike":      ("#828a96", None, False, False, True),
        "code_inline": ("#a8264c", "#f0f2f5", False, False, False),
        "fence":       ("#0d6b45", None, False, False, False),
        "code_body":   ("#3a424c", None, False, False, False),
        "link":        ("#1f6feb", None, False, False, True),
        "url":         ("#6b7480", None, False, False, False),
        "image":       ("#7a3fc4", None, False, False, False),
        "quote":       ("#5a6472", None, False, True, False),
        "list":        ("#9a6700", None, True, False, False),
        "task_done":   ("#1a7f52", None, True, False, False),
        "task_todo":   ("#9a6700", None, True, False, False),
        "hr":          ("#c3c9d2", None, False, False, False),
        "table":       ("#0a4fa8", None, False, False, False),
        "html":        ("#6b7480", None, False, False, False),
    },
}


def _build_format(spec: tuple[str, str | None, bool, bool, bool]) -> QTextCharFormat:
    color, background, bold, italic, underline = spec
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if background:
        fmt.setBackground(QColor(background))
    if bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    fmt.setFontItalic(italic)
    fmt.setFontUnderline(underline)
    return fmt


class MarkdownHighlighter(QSyntaxHighlighter):
    """Realçador de Markdown com suporte a temas."""

    def __init__(self, document: QTextDocument, theme: str = "dark") -> None:
        super().__init__(document)
        self._theme = theme
        self._formats: dict[str, QTextCharFormat] = {}
        self._rules: list[tuple[QRegularExpression, str]] = []
        self._fence_re = QRegularExpression(r"^\s{0,3}(`{3,}|~{3,})")
        self.build_rules()

    # ------------------------------------------------------------------
    # Configuração
    # ------------------------------------------------------------------
    @property
    def theme(self) -> str:
        return self._theme

    def set_theme(self, theme: str) -> None:
        if theme == self._theme:
            return
        self._theme = theme
        self.build_rules()
        self.rehighlight()

    def build_rules(self) -> None:
        """(Re)constrói formatos e regras para o tema atual."""
        palette = PALETTES.get(self._theme, PALETTES["dark"])
        self._formats = {key: _build_format(spec) for key, spec in palette.items()}

        def rx(pattern: str) -> QRegularExpression:
            return QRegularExpression(pattern)

        self._rules = [
            # Títulos: a ordem importa porque estas regras são aplicadas em
            # sequência e as seguintes sobrescrevem as anteriores.
            (rx(r"^\s{0,3}#{1,6}\s.*$"), "heading"),
            (rx(r"^\s{0,3}>\s?.*$"), "quote"),
            (rx(r"^\s{0,3}(?:[-*_])\s*(?:[-*_]\s*){2,}$"), "hr"),
            (rx(r"^\s{0,3}(?:[-*+]|\d+[.)])\s"), "list"),
            (rx(r"^\s{0,3}[-*+]\s\[[xX]\]"), "task_done"),
            (rx(r"^\s{0,3}[-*+]\s\[ \]"), "task_todo"),
            (rx(r"^\s{0,3}\|.*\|\s*$"), "table"),
            # Ênfase
            (rx(r"\*\*(?=\S)(.+?)(?<=\S)\*\*"), "bold"),
            (rx(r"__(?=\S)(.+?)(?<=\S)__"), "bold"),
            (rx(r"(?<![\*\w])\*(?=\S)([^\*\n]+?)(?<=\S)\*(?!\*)"), "italic"),
            (rx(r"(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?!\w)"), "italic"),
            (rx(r"~~(?=\S)(.+?)(?<=\S)~~"), "strike"),
            # Código inline (depois de ênfase, senão `*` dentro de crase vira itálico)
            (rx(r"`[^`\n]+`"), "code_inline"),
            # Imagens antes de links: o padrão de link casaria o miolo da imagem
            (rx(r"!\[[^\]]*\]\([^)]*\)"), "image"),
            (rx(r"\[[^\]]*\]\([^)]*\)"), "link"),
            (rx(r"^\s{0,3}<[^>]+>"), "html"),
        ]

    # ------------------------------------------------------------------
    # Realce
    # ------------------------------------------------------------------
    def highlightBlock(self, text: str) -> None:  # noqa: N802 - assinatura do Qt
        previous = self.previousBlockState()
        in_fence = previous == STATE_FENCED_CODE

        # Cerca de abertura ou fechamento.
        if self._fence_re.match(text).hasMatch():
            self.setFormat(0, len(text), self._formats["fence"])
            self.setCurrentBlockState(STATE_NORMAL if in_fence else STATE_FENCED_CODE)
            return

        if in_fence:
            self.setFormat(0, len(text), self._formats["code_body"])
            self.setCurrentBlockState(STATE_FENCED_CODE)
            return

        self.setCurrentBlockState(STATE_NORMAL)

        for expression, key in self._rules:
            iterator = expression.globalMatch(text)
            fmt = self._formats[key]
            while iterator.hasNext():
                match = iterator.next()
                # O grupo 1, quando existe, isola só o conteúdo (sem os
                # delimitadores), que é o que deve ficar colorido.
                if match.lastCapturedIndex() >= 1:
                    start = match.capturedStart(1)
                    length = match.capturedLength(1)
                else:
                    start = match.capturedStart(0)
                    length = match.capturedLength(0)
                if length > 0:
                    self.setFormat(start, length, fmt)

        # A pontuação fica com a cor do texto: ela foi colorida junto com o
        # grupo quando o delimitador não foi capturado separadamente.
        self._dull_delimiters(text)

    def _dull_delimiters(self, text: str) -> None:
        """Devolve aos delimitadores a cor de texto normal.

        Sem isto, `**negrito**` deixa os asteriscos coloridos junto, o que
        polui bastante a leitura em documentos com muita ênfase.
        """
        if self._theme not in PALETTES:
            return
        plain = self._formats.get("code_body") or _build_format(
            PALETTES[self._theme]["code_body"]
        )
        for pattern in (r"\*\*", r"__", r"~~", r"(?<!\*)\*(?!\*)", r"(?<![\w_])_(?![\w_])"):
            iterator = QRegularExpression(pattern).globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(0), match.capturedLength(0), plain)
