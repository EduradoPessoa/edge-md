"""Liga a barra de busca ao texto do editor.

Cuida do que nenhum dos dois lados deve saber sozinho: manter a lista de
ocorrências em dia conforme o documento muda, decidir qual delas está em foco e
executar as substituições como um passo único no histórico de desfazer.

A substituição de tudo é feita trocando o documento inteiro dentro de um
``beginEditBlock``/``endEditBlock``. Sem esse agrupamento, desfazer uma
substituição global exigiria um ``Ctrl+Z`` por ocorrência — num arquivo com
duzentas ocorrências, duzentos comandos.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QTextCursor

from edgemd.editor_widget import MarkdownEditor
from edgemd.find_bar import FindBar
from edgemd.search import (
    MAX_HIGHLIGHTS,
    Match,
    SearchOptions,
    find_all,
    index_of_match_at,
    pattern_error,
    replace_all_in_text,
)

#: Espera antes de refazer a busca quando o documento muda por edição.
DEBOUNCE_MS = 250

#: Afastamento mínimo da borda ao revelar uma ocorrência.
SCROLL_MARGIN = 3


class SearchController(QObject):
    """Estado da busca de um documento."""

    def __init__(
        self, editor: MarkdownEditor, bar: FindBar, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._editor = editor
        self._bar = bar
        self._matches: tuple[Match, ...] = ()
        self._current = -1
        self._query = ""
        self._options = SearchOptions()

        self._bar.searchChanged.connect(self._on_search_changed)
        self._bar.stepRequested.connect(self.step)
        self._bar.replaceRequested.connect(self.replace_current)
        self._bar.replaceAllRequested.connect(self.replace_all)
        self._bar.closed.connect(self.clear)

        # O texto mudou: as posições das ocorrências ficaram obsoletas. A
        # espera evita recalcular a cada tecla enquanto se digita uma
        # substituição que ainda não terminou.
        self._editor.textChanged.connect(self._schedule_refresh)
        self._editor.cursorPositionChanged.connect(self._on_cursor_moved)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------
    @property
    def matches(self) -> tuple[Match, ...]:
        return self._matches

    @property
    def current_index(self) -> int:
        """Índice da ocorrência em foco, ou -1."""
        return self._current

    @property
    def is_active(self) -> bool:
        return bool(self._query)

    # ------------------------------------------------------------------
    # Busca
    # ------------------------------------------------------------------
    def _on_search_changed(self, query: str, options: SearchOptions) -> None:
        self._query = query
        self._options = options
        # Ao mudar o termo, a seleção anterior não serve mais: a busca começa
        # do começo do documento, e não de onde o cursor parou por acaso.
        self._current = -1
        self.refresh()

    def _schedule_refresh(self) -> None:
        if self._query:
            self._timer.start(DEBOUNCE_MS)

    def refresh(self) -> None:
        """Recalcula as ocorrências e repinta os destaques."""
        self._timer.stop()

        erro = pattern_error(self._query, self._options)
        if erro:
            self._matches = ()
            self._current = -1
            self._editor.clear_search_highlights()
            self._bar.set_result(0, 0, error=erro)
            return

        if not self._query:
            self._matches = ()
            self._current = -1
            self._editor.clear_search_highlights()
            self._bar.set_result(0, 0)
            return

        self._matches = find_all(
            self._editor.toPlainText(), self._query, self._options
        )

        if self._matches:
            # Mantém o foco na ocorrência onde o cursor está; se o cursor não
            # está sobre nenhuma, fica na primeira depois dele, ou volta ao
            # início quando não há nenhuma adiante.
            self._current = self._closest_match_index()
        else:
            self._current = -1

        self._apply_highlights()
        self._report()

    def _closest_match_index(self) -> int:
        posicao = self._editor.textCursor().position()
        sobre = index_of_match_at(self._matches, posicao)
        if sobre >= 0:
            return sobre
        for indice, match in enumerate(self._matches):
            if match.start >= posicao:
                return indice
        return 0

    def _apply_highlights(self) -> None:
        # O destaque é limitado; a contagem não. Num arquivo grande, buscar por
        # "a" casaria dezenas de milhares de vezes e o Qt repintaria tudo isso.
        visiveis = self._matches[:MAX_HIGHLIGHTS]
        self._editor.set_search_highlights(
            [(m.start, m.length) for m in visiveis],
            min(self._current, len(visiveis) - 1),
        )

    def _report(self) -> None:
        total = len(self._matches)
        self._bar.set_result(self._current + 1 if total else 0, total)

    # ------------------------------------------------------------------
    # Navegação
    # ------------------------------------------------------------------
    def step(self, direction: int) -> None:
        """Vai para a próxima ocorrência (``1``) ou a anterior (``-1``)."""
        if not self._matches:
            self.refresh()
            if not self._matches:
                return

        if self._current < 0:
            self._current = 0 if direction >= 0 else len(self._matches) - 1
        else:
            self._current = (self._current + direction) % len(self._matches)

        self._reveal_current()

    def _reveal_current(self) -> None:
        """Seleciona a ocorrência em foco e a traz para a área visível."""
        if not 0 <= self._current < len(self._matches):
            return

        match = self._matches[self._current]
        documento = self._editor.document()
        if match.end > documento.characterCount():
            # O documento mudou entre a busca e a navegação.
            self.refresh()
            return

        cursor = QTextCursor(documento)
        cursor.setPosition(match.start)
        cursor.setPosition(match.end, QTextCursor.MoveMode.KeepAnchor)

        self._editor.setTextCursor(cursor)
        self._editor.ensureCursorVisible()
        self._editor.centerCursor()

        self._apply_highlights()
        self._report()

    def _on_cursor_moved(self) -> None:
        """Acompanha o cursor quando o usuário clica no texto.

        Só faz sentido com a barra aberta; fora disso seria trabalho à toa a
        cada movimento de seta.
        """
        if not self._bar.isVisible() or not self._matches:
            return

        indice = index_of_match_at(self._matches, self._editor.textCursor().position())
        if indice >= 0 and indice != self._current:
            self._current = indice
            self._apply_highlights()
            self._report()

    # ------------------------------------------------------------------
    # Substituição
    # ------------------------------------------------------------------
    def replace_current(self, replacement: str) -> None:
        """Troca a ocorrência em foco e avança para a seguinte."""
        if not self._matches:
            return
        if not 0 <= self._current < len(self._matches):
            return

        match = self._matches[self._current]
        documento = self._editor.document()
        if match.end > documento.characterCount():
            self.refresh()
            return

        cursor = QTextCursor(documento)
        cursor.beginEditBlock()
        cursor.setPosition(match.start)
        cursor.setPosition(match.end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(replacement)
        cursor.endEditBlock()

        # O texto já mudou, então a posição de cada ocorrência seguinte
        # deslocou. Refaz a busca e continua de onde parou.
        self.refresh()
        if self._matches:
            self._current = min(self._current, len(self._matches) - 1)
            self._reveal_current()
        else:
            self._editor.setFocus()

    def replace_all(self, replacement: str) -> int:
        """Troca todas as ocorrências. Devolve quantas foram trocadas."""
        if not self._query:
            return 0

        texto = self._editor.toPlainText()
        novo, quantidade = replace_all_in_text(
            texto, self._query, replacement, self._options
        )
        if quantidade == 0:
            self._report()
            return 0

        documento = self._editor.document()
        cursor = QTextCursor(documento)
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(novo)
        cursor.endEditBlock()

        # Depois de trocar tudo, o termo pode não existir mais (foi substituído
        # por outro texto) — a busca então mostra zero, que é a verdade.
        self.refresh()
        return quantidade

    # ------------------------------------------------------------------
    # Abrir e fechar
    # ------------------------------------------------------------------
    def open_bar(self, *, with_replace: bool = False) -> None:
        """Abre a barra, aproveitando a seleção do editor como termo inicial."""
        selecionado = self._editor.textCursor().selectedText()
        # selectedText troca quebra de linha por U+2029; numa busca de uma
        # linha só isso importa, então normalizamos.
        termo = selecionado.replace("\u2029", "\n").strip()
        if "\n" in termo:
            termo = ""

        self._bar.open_bar(with_replace=with_replace, query=termo)
        if termo:
            self._on_search_changed(termo, self._bar.options)
        else:
            self.refresh()

    def clear(self) -> None:
        """Encerra a busca e remove os destaques."""
        self._timer.stop()
        self._matches = ()
        self._current = -1
        self._editor.clear_search_highlights()
