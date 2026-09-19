"""Barra de localizar e substituir do editor.

Fica dentro da aba, logo abaixo do texto, e não numa janela separada: uma
janela modal tira o foco do documento e obriga a fechar antes de continuar
lendo, enquanto a barra convive com a edição — dá para ver o resultado de cada
substituição sem soltar o teclado.

A barra **não** procura nada sozinha. Ela só monta a consulta e emite sinais; a
busca em si vive em :mod:`edgemd.search` e o destaque no editor. Essa separação
é o que permite testar a lógica de busca sem abrir janela nenhuma.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from edgemd.search import SearchOptions

#: Espera antes de procurar enquanto o usuário digita.
#:
#: Sem isso, cada tecla dispararia uma varredura do documento inteiro e a
#: digitação engasgaria em arquivos grandes.
DEBOUNCE_MS = 180


class FindBar(QWidget):
    """Barra de busca com contador de resultados e opções."""

    #: Termo ou opções mudaram: refazer a busca e destacar.
    searchChanged = pyqtSignal(str, object)
    #: Ir para a próxima ocorrência (``-1`` para a anterior).
    stepRequested = pyqtSignal(int)
    #: Substituir a ocorrência atual.
    replaceRequested = pyqtSignal(str)
    #: Substituir todas.
    replaceAllRequested = pyqtSignal(str)
    #: A barra foi fechada.
    closed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("findBar")
        # A barra não deve aparecer no ciclo de foco do Tab.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._options = SearchOptions()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._emit_search)

        # -- linha 1: localizar ------------------------------------------
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Localizar")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumWidth(200)
        self.search_input.textChanged.connect(lambda _t: self._timer.start(DEBOUNCE_MS))
        self.search_input.returnPressed.connect(lambda: self.stepRequested.emit(1))

        self.previous_button = self._step_button(
            "↑", "Ocorrência anterior (Shift+F3)", -1
        )
        self.next_button = self._step_button(
            "↓", "Próxima ocorrência (F3)", 1
        )

        self.count_label = QLabel("")
        self.count_label.setObjectName("findCount")
        self.count_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.case_button = self._toggle_button("Aa", "Diferenciar maiúsculas de minúsculas")
        self.word_button = self._toggle_button("ab", "Palavra inteira")
        self.regex_button = self._toggle_button(".*", "Expressão regular")

        self.close_button = QToolButton()
        self.close_button.setText("✕")
        self.close_button.setObjectName("findToggle")
        self.close_button.setToolTip("Fechar a busca (Esc)")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self.close_bar)

        primeira = QHBoxLayout()
        primeira.setContentsMargins(0, 0, 0, 0)
        primeira.setSpacing(4)
        primeira.addWidget(self.search_input, 1)
        primeira.addWidget(self.count_label)
        primeira.addWidget(self.previous_button)
        primeira.addWidget(self.next_button)
        for botao in (self.case_button, self.word_button, self.regex_button):
            primeira.addWidget(botao)
        primeira.addWidget(self.close_button)

        # -- linha 2: substituir -----------------------------------------
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Substituir por")
        self.replace_input.returnPressed.connect(self._on_replace)
        self.replace_input.textChanged.connect(self._update_replace_enabled)

        self.replace_button = QToolButton()
        self.replace_button.setText("Substituir")
        self.replace_button.setObjectName("findToggle")
        self.replace_button.setToolTip("Substituir a ocorrência atual")
        self.replace_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.replace_button.clicked.connect(self._on_replace)

        self.replace_all_button = QToolButton()
        self.replace_all_button.setText("Substituir tudo")
        self.replace_all_button.setObjectName("findToggle")
        self.replace_all_button.setToolTip(
            "Substituir todas as ocorrências de uma vez"
        )
        self.replace_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.replace_all_button.clicked.connect(
            lambda: self.replaceAllRequested.emit(self.replace_input.text())
        )

        segunda = QHBoxLayout()
        segunda.setContentsMargins(0, 0, 0, 0)
        segunda.setSpacing(4)
        segunda.addWidget(self.replace_input, 1)
        segunda.addWidget(self.replace_button)
        segunda.addWidget(self.replace_all_button)

        self._replace_row = QWidget()
        self._replace_row.setLayout(segunda)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(5)
        layout.addLayout(primeira)
        layout.addWidget(self._replace_row)

        self._error_label = QLabel("")
        self._error_label.setObjectName("findError")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        self._update_replace_enabled()

    # ------------------------------------------------------------------
    # Montagem
    # ------------------------------------------------------------------
    def _step_button(self, texto: str, dica: str, passo: int) -> QToolButton:
        botao = QToolButton()
        botao.setText(texto)
        botao.setObjectName("findToggle")
        botao.setToolTip(dica)
        botao.setCursor(Qt.CursorShape.PointingHandCursor)
        botao.clicked.connect(lambda: self.stepRequested.emit(passo))
        return botao

    def _toggle_button(self, texto: str, dica: str) -> QToolButton:
        botao = QToolButton()
        botao.setText(texto)
        botao.setObjectName("findToggle")
        botao.setCheckable(True)
        botao.setToolTip(dica)
        botao.setCursor(Qt.CursorShape.PointingHandCursor)
        botao.toggled.connect(self._on_option_toggled)
        return botao

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------
    @property
    def query(self) -> str:
        return self.search_input.text()

    @property
    def replacement(self) -> str:
        return self.replace_input.text()

    @property
    def options(self) -> SearchOptions:
        return self._options

    def set_replace_visible(self, visible: bool) -> None:
        self._replace_row.setVisible(visible)

    def replace_visible(self) -> bool:
        """True quando a linha de substituição está aberta.

        ``isHidden`` em vez de ``isVisible``: o segundo é falso enquanto a
        janela não estiver na tela, e a linha seria dada como fechada só por o
        app estar na bandeja.
        """
        return not self._replace_row.isHidden()

    def _on_option_toggled(self, _marcado: bool) -> None:
        self._options = SearchOptions(
            case_sensitive=self.case_button.isChecked(),
            whole_word=self.word_button.isChecked(),
            regex=self.regex_button.isChecked(),
        )
        self.search_input.setPlaceholderText(
            "Expressão regular" if self._options.regex else "Localizar"
        )
        # Refaz na hora, sem esperar o debounce: clicar numa opção é uma ação
        # deliberada, e o usuário espera ver o efeito imediatamente.
        self._emit_search()

    def _emit_search(self) -> None:
        self._timer.stop()
        self.searchChanged.emit(self.query, self._options)

    def _on_replace(self) -> None:
        self.replaceRequested.emit(self.replace_input.text())

    def _update_replace_enabled(self) -> None:
        tem_termo = bool(self.replace_input.text())
        self.replace_button.setEnabled(tem_termo)
        self.replace_all_button.setEnabled(tem_termo)

    # ------------------------------------------------------------------
    # Retorno da busca
    # ------------------------------------------------------------------
    def set_result(self, current: int, total: int, error: str | None = None) -> None:
        """Mostra o contador e o estado de erro.

        ``current`` é 1-based; zero significa "nenhuma ocorrência em foco".
        """
        if error:
            self._error_label.setText(error)
            self._error_label.setVisible(True)
            self.count_label.setText("")
        else:
            self._error_label.setVisible(False)
            if total == 0:
                self.count_label.setText("nenhum" if self.query else "")
            else:
                self.count_label.setText(f"{current} de {total}")

        sem_resultado = bool(self.query) and total == 0 and not error
        # O Qt só repinta o campo quando a propriedade muda de valor, então
        # isto é o que acende a borda vermelha quando a busca não acha nada.
        self.search_input.setProperty("noResults", "true" if sem_resultado else "false")
        self.search_input.style().unpolish(self.search_input)
        self.search_input.style().polish(self.search_input)

        tem_resultado = total > 0
        self.previous_button.setEnabled(tem_resultado)
        self.next_button.setEnabled(tem_resultado)

    # ------------------------------------------------------------------
    # Abrir e fechar
    # ------------------------------------------------------------------
    def open_bar(self, *, with_replace: bool = False, query: str = "") -> None:
        """Mostra a barra e coloca o foco no campo de busca.

        Se houver texto selecionado no editor, ele vem como termo inicial — é o
        que o usuário espera ao selecionar uma palavra e apertar Ctrl+F.
        """
        self.set_replace_visible(with_replace)
        if query:
            # Substituir o texto por ele mesmo não emite textChanged quando é
            # igual, então a busca precisa ser disparada à mão.
            ja_igual = self.search_input.text() == query
            self.search_input.setText(query)
            if ja_igual:
                self._emit_search()
        self.show()
        self.search_input.setFocus()
        self.search_input.selectAll()

    def close_bar(self) -> None:
        self._timer.stop()
        self.hide()
        self.closed.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - assinatura do Qt
        if event.key() == Qt.Key.Key_Escape:
            self.close_bar()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.stepRequested.emit(-1)
            else:
                self.stepRequested.emit(1)
            return
        super().keyPressEvent(event)

    def actions(self) -> list[QAction]:
        """Atalhos internos da barra.

        Ficam na barra, e não na janela, para não dispararem quando ela está
        escondida — o ``Ctrl+F`` da janela reabre a barra em vez de conflitar.
        """
        proximo_shift = QAction(self)
        proximo_shift.setShortcut(QKeySequence("Shift+F3"))
        proximo_shift.triggered.connect(lambda: self.stepRequested.emit(-1))
        self.addAction(proximo_shift)
        return [proximo_shift]
