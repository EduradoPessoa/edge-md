"""Diálogos de inserção de link e de imagem.

Diálogo, e não inserção direta com espaço reservado selecionado: o atalho antigo
escrevia ``[texto](url)`` e deixava a palavra "url" selecionada para o usuário
digitar por cima. Funciona, mas erra em dois casos comuns — colar um endereço
longo, e usar um texto diferente do endereço. Com campos separados dá para ver
os dois, conferir e corrigir antes de inserir.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from edgemd.image_insert import DEFAULT_ASSETS_FOLDER


class LinkDialog(QDialog):
    """Pede o texto e o endereço de um link."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        text: str = "",
        url: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Inserir link")
        self.setModal(True)
        self.setMinimumWidth(420)

        self.text_input = QLineEdit(text)
        self.text_input.setPlaceholderText("Texto que aparece no documento")

        self.url_input = QLineEdit(url)
        self.url_input.setPlaceholderText("https://exemplo.com ou outro.md#secao")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Texto:", self.text_input)
        form.addRow("Endereço:", self.url_input)

        self._hint = QLabel(
            "Deixe o texto em branco para usar o próprio endereço."
        )
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: palette(mid); font-size: 11px;")

        botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        self._ok = botoes.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setText("Inserir")

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._hint)
        layout.addWidget(botoes)

        # Sem endereço não há link: o botão fica desligado até haver um.
        self.url_input.textChanged.connect(self._update_ok)
        self._update_ok()

        # O campo com que o usuário veio preenchido recebe o foco.
        (self.url_input if text else self.text_input).setFocus()

    def _update_ok(self) -> None:
        self._ok.setEnabled(bool(self.url_input.text().strip()))

    @property
    def link_text(self) -> str:
        """Texto do link; cai para o endereço quando em branco."""
        return self.text_input.text().strip() or self.url_input.text().strip()

    @property
    def link_url(self) -> str:
        return self.url_input.text().strip()

    @classmethod
    def ask(
        cls, parent: QWidget | None, *, text: str = "", url: str = ""
    ) -> tuple[str, str] | None:
        """Abre o diálogo e devolve ``(texto, endereço)``, ou None se cancelado."""
        dialogo = cls(parent, text=text, url=url)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialogo.link_text, dialogo.link_url


class ImageDialog(QDialog):
    """Pede o texto alternativo e a decisão sobre copiar a imagem."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        alt: str = "",
        can_copy: bool = False,
        source: str = "",
        folder: str = DEFAULT_ASSETS_FOLDER,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Inserir imagem")
        self.setModal(True)
        self.setMinimumWidth(460)

        self.alt_input = QLineEdit(alt)
        self.alt_input.setPlaceholderText("Descrição da imagem")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Texto alternativo:", self.alt_input)

        if source:
            origem = QLabel(Path(source).name)
            origem.setToolTip(source)
            form.addRow("Arquivo:", origem)

        # O texto alternativo não é enfeite: é o que o leitor de tela lê e o que
        # aparece quando a imagem não carrega. Vale explicar isso na tela.
        self._hint = QLabel(
            "O texto alternativo aparece quando a imagem não carrega e é lido "
            "por leitores de tela."
        )
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: palette(mid); font-size: 11px;")

        self.copy_check = QCheckBox(
            f"Copiar para a pasta do documento ({folder}/)"
        )
        self.copy_check.setChecked(can_copy)
        self.copy_check.setVisible(can_copy)
        # Guardado à parte porque a decisão não pode depender de o widget estar
        # visível na tela: `isVisible` é falso enquanto o diálogo não é exibido.
        self._can_copy = can_copy
        if can_copy:
            self.copy_check.setToolTip(
                "Sem copiar, o documento guardaria um caminho absoluto desta "
                "máquina e a imagem não apareceria em outro computador."
            )

        botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        botoes.button(QDialogButtonBox.StandardButton.Ok).setText("Inserir")

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._hint)
        if can_copy:
            layout.addWidget(self.copy_check)
        layout.addWidget(botoes)

        self.alt_input.setFocus()
        self.alt_input.selectAll()

    @property
    def alt(self) -> str:
        return self.alt_input.text().strip()

    @property
    def copy_external(self) -> bool:
        return self._can_copy and self.copy_check.isChecked()

    @classmethod
    def ask(
        cls,
        parent: QWidget | None,
        *,
        alt: str = "",
        can_copy: bool = False,
        source: str = "",
        folder: str = DEFAULT_ASSETS_FOLDER,
    ) -> tuple[str, bool] | None:
        """Devolve ``(texto_alternativo, copiar)``, ou None se cancelado."""
        dialogo = cls(
            parent, alt=alt, can_copy=can_copy, source=source, folder=folder
        )
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialogo.alt, dialogo.copy_external
