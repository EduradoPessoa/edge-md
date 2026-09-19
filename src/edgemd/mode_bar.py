"""Faixa de modo: o componente que entra e sai da edição.

O app abre em modo de leitura. Para editar, o usuário clica em **Editar** nesta
faixa; para voltar a ler, clica em **Concluir**.

Por que uma faixa e não um botão flutuante sobre o preview: o
``QWebEngineView`` desenha pelo compositor do Chromium, que não participa da
pintura normal de widgets do Qt. Um widget filho posicionado sobre ele
simplesmente não aparece. Uma faixa própria ao lado do preview é confiável e
ainda dá espaço para mostrar qual arquivo está aberto.

A aparência vem do QSS global (``edgemd.theme``), que estiliza pelos
``objectName`` definidos aqui. Este módulo não carrega folha de estilo própria
justamente para o tema ser um só em todo o aplicativo.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class ModeBar(QWidget):
    """Barra com o nome do arquivo e o botão de troca de modo."""

    editRequested = pyqtSignal()
    readRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("modeBar")

        self._label = QLabel("")
        self._label.setObjectName("modeBarLabel")
        # O nome pode ser longo; elidir no meio preserva a extensão e o começo,
        # que é o que identifica o arquivo.
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._full_text = ""

        self._button = QPushButton("Editar")
        self._button.setObjectName("modeBarButton")
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._button.setToolTip("Abrir o editor deste documento")
        self._button.clicked.connect(self._on_clicked)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 5, 8, 5)
        layout.setSpacing(8)
        layout.addWidget(self._label, 1)
        layout.addWidget(self._button)

        self._mode = "preview"

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------
    def set_document_name(self, name: str, *, dirty: bool = False) -> None:
        """Mostra o nome do documento aberto, com marca de alteração."""
        self._full_text = name
        self._label.setText(("• " if dirty else "") + name)
        self._label.setToolTip(name)

    def set_mode(self, mode: str) -> None:
        """Ajusta rótulo e dica do botão conforme o modo atual."""
        self._mode = mode
        if mode == "preview":
            self._button.setText("Editar")
            self._button.setToolTip("Abrir o editor deste documento")
        else:
            self._button.setText("Concluir")
            self._button.setToolTip("Voltar para a leitura")

    def _on_clicked(self) -> None:
        if self._mode == "preview":
            self.editRequested.emit()
        else:
            self.readRequested.emit()
