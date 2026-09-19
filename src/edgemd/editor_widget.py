"""Widget de edição de Markdown.

Um ``QPlainTextEdit`` com o que falta nele para editar Markdown de verdade:
numeração de linhas, realce da linha atual, indentação com espaços e — o
detalhe que mais incomoda quando não existe — continuação automática de listas
ao pressionar Enter.
"""

from __future__ import annotations

import re

from PyQt6.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QPainter,
    QTextCursor,
    QTextOption,
)
from PyQt6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from edgemd.md_highlighter import MarkdownHighlighter

#: Cores da moldura do editor por tema.
#: (fundo, texto, fundo da calha, texto da calha, linha atual, seleção)
EDITOR_COLORS: dict[str, tuple[str, str, str, str, str, str]] = {
    "dark": ("#16181d", "#e4e7ee", "#1a1d23", "#5a6272", "#1c1f26", "#2f4a6d"),
    "light": ("#ffffff", "#1f2328", "#f5f6f8", "#9aa2ad", "#f7f8fa", "#cfe3ff"),
}

#: Reconhece o prefixo de um item de lista, para continuar a lista no Enter.
#: grupo 1 = indentação, grupo 2 = marcador, grupo 3 = caixa de tarefa
LIST_ITEM = re.compile(
    r"^(\s*)(?:(?:[-*+])\s+(\[[ xX]\]\s+)?|(\d+)([.)])\s+)"
)


def _pick_mono_font() -> str:
    """Primeira família monoespaçada disponível no sistema."""
    available = set(QFontDatabase.families())
    for candidate in (
        "Cascadia Code",
        "Cascadia Mono",
        "JetBrains Mono",
        "Fira Code",
        "Consolas",
        "Courier New",
    ):
        if candidate in available:
            return candidate
    return "monospace"


class LineNumberArea(QWidget):
    """Calha lateral com os números de linha."""

    def __init__(self, editor: "MarkdownEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802 - assinatura do Qt
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802 - assinatura do Qt
        self._editor.paint_line_numbers(event)


class MarkdownEditor(QPlainTextEdit):
    """Área de edição de Markdown."""

    #: Emitido quando a linha do cursor muda (1-based).
    cursorLineChanged = pyqtSignal(int)

    def __init__(self, theme: str = "dark", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._line_numbers_visible = True
        self._font_size = 14

        self._gutter = LineNumberArea(self)
        self._base_font = QFont(_pick_mono_font(), self._font_size)
        self.setFont(self._base_font)

        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setCursorWidth(2)

        self._highlighter = MarkdownHighlighter(self.document(), theme)
        self.apply_theme(theme)

        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._on_cursor_moved)

        self._update_gutter_width()
        self._highlight_current_line()

    # ------------------------------------------------------------------
    # Aparência
    # ------------------------------------------------------------------
    def apply_theme(self, theme: str) -> None:
        self._theme = theme if theme in EDITOR_COLORS else "dark"
        bg, fg, gutter_bg, gutter_fg, current, selection = EDITOR_COLORS[self._theme]

        self.setStyleSheet(
            f"QPlainTextEdit {{"
            f" background-color: {bg};"
            f" color: {fg};"
            f" border: 0;"
            f" selection-background-color: {selection};"
            f"}}"
        )
        self._gutter.setStyleSheet(f"background-color: {gutter_bg};")
        self._gutter_fg = QColor(gutter_fg)
        self._gutter_bg = QColor(gutter_bg)
        self._current_line_color = QColor(current)

        self._highlighter.set_theme(self._theme)
        self._highlight_current_line()
        self._gutter.update()

    def set_font_size(self, size: int) -> None:
        self._font_size = max(8, min(32, int(size)))
        self._base_font.setPointSize(self._font_size)
        self.setFont(self._base_font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self._update_gutter_width()
        self._highlight_current_line()

    @property
    def font_size(self) -> int:
        return self._font_size

    def set_line_numbers_visible(self, visible: bool) -> None:
        self._line_numbers_visible = bool(visible)
        self._gutter.setVisible(self._line_numbers_visible)
        self._update_gutter_width()

    def set_word_wrap(self, enabled: bool) -> None:
        self.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if enabled
            else QPlainTextEdit.LineWrapMode.NoWrap
        )

    # ------------------------------------------------------------------
    # Calha de números
    # ------------------------------------------------------------------
    def line_number_area_width(self) -> int:
        if not self._line_numbers_visible:
            return 0
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter_width(self) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_gutter(self, rect: QRect, dy: int) -> None:
        if not self._line_numbers_visible:
            return
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event) -> None:  # noqa: N802 - assinatura do Qt
        super().resizeEvent(event)
        area = self.contentsRect()
        self._gutter.setGeometry(
            QRect(area.left(), area.top(), self.line_number_area_width(), area.height())
        )

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), self._gutter_bg)

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        bottom = top + round(self.blockBoundingRect(block).height())
        current_line = self.textCursor().blockNumber()

        painter.setFont(self._base_font)
        height = self.fontMetrics().height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                # A linha do cursor fica destacada na calha: ajuda a achar a
                # posição ao voltar para uma aba depois de um tempo.
                if block_number == current_line:
                    painter.setPen(self._gutter_fg.lighter(160))
                else:
                    painter.setPen(self._gutter_fg)
                painter.drawText(
                    0,
                    top,
                    self._gutter.width() - 6,
                    height,
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                    number,
                )

            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    # ------------------------------------------------------------------
    # Linha atual
    # ------------------------------------------------------------------
    def _highlight_current_line(self) -> None:
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(self._current_line_color)
        selection.format.setProperty(
            # Faz o fundo cobrir a largura toda, e não só até o fim do texto.
            0x1000,  # QTextFormat.Property.FullWidthSelection
            True,
        )
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])

    def _on_cursor_moved(self) -> None:
        self._highlight_current_line()
        self._gutter.update()
        self.cursorLineChanged.emit(self.current_line())

    def current_line(self) -> int:
        """Linha do cursor, 1-based."""
        return self.textCursor().blockNumber() + 1

    # ------------------------------------------------------------------
    # Edição
    # ------------------------------------------------------------------
    def keyPressEvent(self, event) -> None:  # noqa: N802 - assinatura do Qt
        key = event.key()

        # Tab insere espaços (largura vinda do tabStopDistance).
        if key == Qt.Key.Key_Tab and not event.modifiers():
            self._insert_spaces()
            return
        if key == Qt.Key.Key_Backtab:
            self._unindent()
            return

        # Enter continua listas, citações e caixas de tarefa.
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers():
            if self._continue_block():
                return

        super().keyPressEvent(event)

    def _insert_spaces(self) -> None:
        spaces = max(1, self.tab_width())
        cursor = self.textCursor()
        if cursor.hasSelection():
            self.indent_selection()
            return
        cursor.insertText(" " * spaces)
        self.setTextCursor(cursor)

    def tab_width(self) -> int:
        advance = self.fontMetrics().horizontalAdvance(" ")
        if advance <= 0:
            return 4
        return max(2, min(8, round(self.tabStopDistance() / advance)))

    def _unindent(self) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection():
            self.unindent_selection()
            return
        block = cursor.block()
        text = block.text()
        remove = 0
        while remove < len(text) and remove < self.tab_width() and text[remove] == " ":
            remove += 1
        if remove:
            cursor.movePosition(
                QTextCursor.MoveOperation.StartOfBlock,
                QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.removeSelectedText()
            self.setTextCursor(cursor)

    def indent_selection(self) -> None:
        self._shift_selection(indent=True)

    def unindent_selection(self) -> None:
        self._shift_selection(indent=False)

    def _shift_selection(self, indent: bool) -> None:
        cursor = self.textCursor()
        start_block = self.document().findBlock(cursor.selectionStart()).blockNumber()
        end_block = self.document().findBlock(cursor.selectionEnd()).blockNumber()
        spaces = " " * self.tab_width()

        edit = QTextCursor(self.document())
        edit.beginEditBlock()
        for number in range(start_block, end_block + 1):
            block = self.document().findBlockByNumber(number)
            line = QTextCursor(block)
            if indent:
                line.insertText(spaces)
            else:
                text = block.text()
                remove = 0
                while (
                    remove < len(text)
                    and remove < self.tab_width()
                    and text[remove] == " "
                ):
                    remove += 1
                if remove:
                    line.movePosition(
                        QTextCursor.MoveOperation.Right,
                        QTextCursor.MoveMode.KeepAnchor,
                        remove,
                    )
                    line.removeSelectedText()
        edit.endEditBlock()

    def _continue_block(self) -> bool:
        """Continua lista/citação na linha nova. True se tratou o Enter."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            return False

        line = cursor.block().text()
        match = LIST_ITEM.match(line)

        if not match:
            # Citação e caixa de tarefa solta.
            quote = re.match(r"^(\s*>\s?)", line)
            if quote and not line.strip().rstrip(">").strip() == "":
                cursor.insertText("\n" + quote.group(1))
                self.setTextCursor(cursor)
                return True
            return False

        indent, _marker, number, delimiter = (
            match.group(1),
            match.group(2),
            match.group(3),
            match.group(4),
        )

        # Enter num item vazio encerra a lista, como em qualquer editor decente.
        content = line[match.end():].strip()
        if not content:
            block_cursor = QTextCursor(cursor.block())
            block_cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            block_cursor.removeSelectedText()
            self.setTextCursor(block_cursor)
            return True

        if number is not None:
            prefix = f"{indent}{int(number) + 1}{delimiter} "
        else:
            prefix = f"{indent}{line.lstrip()[0]} "

        cursor.insertText("\n" + prefix)
        self.setTextCursor(cursor)
        return True

    def insert_surround(self, before: str, after: str = "", placeholder: str = "") -> None:
        """Envolve a seleção com marcadores (negrito, itálico, código).

        Sem seleção, insere os marcadores e deixa o cursor no meio; com
        seleção, envolve o texto já escolhido.
        """
        cursor = self.textCursor()
        selected = cursor.selectedText()

        if selected:
            cursor.insertText(f"{before}{selected}{after}")
            self.setTextCursor(cursor)
            return

        text = placeholder or ""
        cursor.insertText(f"{before}{text}{after}")
        if text:
            # Seleciona o espaço reservado para o usuário digitar por cima.
            for _ in range(len(after) + len(text)):
                cursor.movePosition(QTextCursor.MoveOperation.Left)
            for _ in range(len(text)):
                cursor.movePosition(
                    QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor
                )
        else:
            for _ in range(len(after)):
                cursor.movePosition(QTextCursor.MoveOperation.Left)
        self.setTextCursor(cursor)

    def insert_link(self) -> None:
        """Insere um link, usando a seleção como texto do rótulo."""
        cursor = self.textCursor()
        selected = cursor.selectedText() or "texto"
        cursor.insertText(f"[{selected}](url)")
        # Deixa "url" selecionado para digitar por cima.
        for _ in range(5):
            cursor.movePosition(QTextCursor.MoveOperation.Left)
        for _ in range(3):
            cursor.movePosition(
                QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor
            )
        self.setTextCursor(cursor)

    def insert_line_prefix(self, prefix: str) -> None:
        """Alterna um prefixo no início da linha (título, citação, lista)."""
        cursor = self.textCursor()
        block = cursor.block()
        text = block.text()
        stripped = text.lstrip()
        indent = text[: len(text) - len(stripped)]

        line_cursor = QTextCursor(block)
        line_cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        line_cursor.removeSelectedText()
        line_cursor.insertText(f"{indent}{prefix}{stripped}" if stripped else prefix)
        self.setTextCursor(line_cursor)

    def goto_line(self, line: int) -> None:
        """Coloca o cursor numa linha (1-based) e centraliza a visão."""
        block = self.document().findBlockByNumber(max(0, int(line) - 1))
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        self.setTextCursor(cursor)
        self.centerCursor()

    def scroll_to_line(self, line: int) -> None:
        """Rola até uma linha **sem mover o cursor**.

        É o que a sincronia de scroll do preview precisa. Usar ``goto_line``
        aqui moveria o cursor enquanto o usuário apenas lê o preview, e o
        próximo caractere digitado cairia no lugar errado.
        """
        block = self.document().findBlockByNumber(max(0, int(line) - 1))
        if not block.isValid():
            return
        rect = self.blockBoundingGeometry(block).translated(self.contentOffset())
        self.verticalScrollBar().setValue(int(rect.top()))
