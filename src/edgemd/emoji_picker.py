"""Seletor de emoji, em popup ancorado no botão da barra.

Popup, e não diálogo modal: o emoji é inserido no meio do texto, e um diálogo
que precisa ser fechado antes de continuar escrevendo interrompe a escrita. O
popup fecha ao clicar fora, e a busca recebe o foco para quem prefere digitar
"foguete" em vez de procurar na grade.

A grade é montada com botões comuns em vez de uma view virtualizada: são ~380
itens, e a diferença de desempenho não se percebe, enquanto a de complexidade é
grande.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from edgemd import emojis
from edgemd.emojis import Emoji

#: Colunas da grade. 10 cabe com folga numa janela estreita e evita rolagem
#: horizontal.
COLUNAS = 10

#: Lado de cada botão, em pixels.
LADO_BOTAO = 34

#: Quantos resultados mostrar numa busca. Sem limite, procurar por "a" traria
#: quase o catálogo inteiro e a grade ficaria enorme sem ajudar.
LIMITE_BUSCA = 120


class EmojiPicker(QFrame):
    """Grade de emojis com busca e filtro por categoria."""

    #: Emitido com o caractere escolhido.
    emojiChosen = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("emojiPicker")
        # Popup: fecha sozinho ao clicar fora, como um menu.
        self.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumSize(380, 320)

        self._categoria_atual: str | None = None

        # -- busca -------------------------------------------------------
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar emoji…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search)
        self.search_input.returnPressed.connect(self._choose_first)

        # -- categorias ---------------------------------------------------
        self._category_buttons: dict[str | None, QToolButton] = {}
        categorias = QHBoxLayout()
        categorias.setContentsMargins(0, 0, 0, 0)
        categorias.setSpacing(3)
        for nome in (None, *emojis.categories()):
            rotulo = "Todos" if nome is None else nome
            botao = QToolButton()
            botao.setText(rotulo)
            botao.setObjectName("emojiCategory")
            botao.setCheckable(True)
            botao.setCursor(Qt.CursorShape.PointingHandCursor)
            botao.setToolTip(f"Mostrar {rotulo.lower()}")
            botao.clicked.connect(
                lambda _checked=False, n=nome: self._on_category(n)
            )
            self._category_buttons[nome] = botao
            categorias.addWidget(botao)
        categorias.addStretch(1)

        # -- grade --------------------------------------------------------
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(6, 6, 6, 6)
        self._grid.setSpacing(2)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._grid_host)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._empty_label = QLabel("Nenhum emoji encontrado")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: palette(mid);")
        self._empty_label.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self.search_input)
        layout.addLayout(categorias)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(self._empty_label)

        self._set_category(None)

    # ------------------------------------------------------------------
    # Montagem da grade
    # ------------------------------------------------------------------
    def _set_category(self, categoria: str | None) -> None:
        self._categoria_atual = categoria
        for nome, botao in self._category_buttons.items():
            botao.setChecked(nome == categoria)
        self.search_input.clear()
        self._fill(
            emojis.all_emojis() if categoria is None else emojis.by_category(categoria)
        )

    def _on_category(self, categoria: str | None) -> None:
        if categoria == self._categoria_atual and not self.search_input.text():
            return
        self._set_category(categoria)

    def _on_search(self, _texto: str) -> None:
        termo = self.search_input.text().strip()
        if not termo:
            self._fill(
                emojis.all_emojis()
                if self._categoria_atual is None
                else emojis.by_category(self._categoria_atual)
            )
            return

        encontrados = emojis.search(termo, limit=LIMITE_BUSCA)
        # A busca atravessa todas as categorias de propósito: quem digita
        # "bug" não sabe em qual categoria o emoji mora.
        self._fill(encontrados)

    def _fill(self, lista: tuple[Emoji, ...]) -> None:
        self._limpar_grade()

        if not lista:
            self._scroll.hide()
            self._empty_label.show()
            return

        self._empty_label.hide()
        self._scroll.show()

        for indice, emoji in enumerate(lista):
            botao = QToolButton()
            botao.setText(emoji.char)
            botao.setObjectName("emojiItem")
            botao.setToolTip(emoji.name)
            botao.setCursor(Qt.CursorShape.PointingHandCursor)
            botao.setFixedSize(LADO_BOTAO, LADO_BOTAO)
            botao.clicked.connect(
                lambda _checked=False, c=emoji.char: self.emojiChosen.emit(c)
            )
            self._grid.addWidget(botao, indice // COLUNAS, indice % COLUNAS)

        # Empurra tudo para o topo quando a lista é curta.
        self._grid.setRowStretch(self._grid.rowCount(), 1)

    def _limpar_grade(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _choose_first(self) -> None:
        """Enter na busca insere o primeiro resultado."""
        resultados = emojis.search(self.search_input.text(), limit=1)
        if resultados:
            self.emojiChosen.emit(resultados[0].char)

    # ------------------------------------------------------------------
    # Exibição
    # ------------------------------------------------------------------
    def open_at(self, anchor: QWidget) -> None:
        """Mostra o popup logo abaixo de ``anchor``, alinhado à direita."""
        from PyQt6.QtGui import QGuiApplication

        self._set_category(self._categoria_atual)
        self.adjustSize()

        canto = anchor.mapToGlobal(anchor.rect().bottomRight())
        x = canto.x() - self.width()
        y = canto.y() + 4

        # Não deixa o popup sair da tela: se não couber embaixo, sobe.
        tela = QGuiApplication.screenAt(canto) or QGuiApplication.primaryScreen()
        if tela is not None:
            area = tela.availableGeometry()
            x = max(area.left() + 8, min(x, area.right() - self.width() - 8))
            if y + self.height() > area.bottom():
                y = max(area.top() + 8, canto.y() - anchor.height() - self.height() - 8)

        self.move(x, y)
        self.show()
        self.search_input.setFocus()

    def count(self) -> int:
        """Quantos itens estão na grade agora. Usado pelos testes."""
        return sum(
            1
            for i in range(self._grid.count())
            if self._grid.itemAt(i).widget() is not None
        )
