"""Diálogo de escolha de modelo, com prévia.

A prévia existe porque nome de modelo não diz o que ele contém. "Documentação
de projeto" pode ser um README curto ou um documento com dez seções, e a
diferença só aparece quando se lê o conteúdo — melhor descobrir antes de criar
o arquivo do que depois.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from edgemd import templates
from edgemd.templates import Template


class TemplatePicker(QDialog):
    """Lista de modelos à esquerda, prévia à direita."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str = "Novo a partir de modelo",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(760, 480)
        self._chosen: Template | None = None

        # -- lista --------------------------------------------------------
        self.list = QListWidget()
        self.list.setMinimumWidth(230)
        self.list.currentItemChanged.connect(self._on_selection)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())

        self._populate(templates.all_templates(include_blank=True))

        # -- prévia -------------------------------------------------------
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.preview.setPlaceholderText("Selecione um modelo para ver o conteúdo.")

        self.description = QLabel("")
        self.description.setWordWrap(True)
        self.description.setStyleSheet("color: palette(mid); font-size: 11px;")

        previa = QWidget()
        previa_layout = QVBoxLayout(previa)
        previa_layout.setContentsMargins(0, 0, 0, 0)
        previa_layout.setSpacing(6)
        previa_layout.addWidget(self.description)
        previa_layout.addWidget(self.preview, 1)

        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.addWidget(self.list)
        divisor.addWidget(previa)
        divisor.setStretchFactor(0, 0)
        divisor.setStretchFactor(1, 1)
        divisor.setSizes([240, 500])

        # -- botões -------------------------------------------------------
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Criar")

        self.delete_button = QPushButton("Excluir modelo")
        self.delete_button.setToolTip("Remover o modelo selecionado")
        self.delete_button.clicked.connect(self._on_delete)
        self.buttons.addButton(self.delete_button, QDialogButtonBox.ButtonRole.ResetRole)

        layout = QVBoxLayout(self)
        layout.addWidget(divisor, 1)
        layout.addWidget(self.buttons)

        if self.list.count():
            self.list.setCurrentRow(0)

    # ------------------------------------------------------------------
    def _populate(self, modelos: list[Template]) -> None:
        self.list.clear()
        for modelo in modelos:
            item = QListWidgetItem(modelo.name)
            item.setData(Qt.ItemDataRole.UserRole, modelo)
            if modelo.is_builtin and modelo.content:
                # O sufixo avisa que salvar por cima cria uma cópia editável,
                # em vez de alterar o modelo que veio com o app.
                item.setToolTip("Modelo que acompanha o app")
            self.list.addItem(item)

    def _current(self) -> Template | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_selection(self) -> None:
        modelo = self._current()
        if modelo is None:
            return

        self.description.setText(modelo.description or "")
        self.preview.setPlainText(modelo.content)
        # Só modelos do usuário podem ser excluídos: os embutidos não têm
        # arquivo, e apagar não faria sentido.
        self.delete_button.setEnabled(modelo.editable)

    def _on_delete(self) -> None:
        modelo = self._current()
        if modelo is None or not modelo.editable:
            return

        from PyQt6.QtWidgets import QMessageBox

        resposta = QMessageBox.question(
            self,
            "Excluir modelo",
            f"Excluir o modelo “{modelo.name}”?\n\nO arquivo será removido da "
            "pasta de modelos.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return

        if templates.delete(modelo.name):
            linha = self.list.currentRow()
            self._populate(templates.all_templates(include_blank=True))
            # Mantém a seleção perto de onde estava, em vez de pular para o
            # começo da lista depois de cada exclusão.
            self.list.setCurrentRow(min(linha, self.list.count() - 1))

    # ------------------------------------------------------------------
    @property
    def chosen(self) -> Template | None:
        """Modelo escolhido, ou None se o diálogo foi cancelado."""
        return self._chosen

    def accept(self) -> None:  # noqa: D102 - assinatura do Qt
        self._chosen = self._current()
        super().accept()

    @classmethod
    def ask(cls, parent: QWidget | None = None) -> Template | None:
        """Abre o diálogo e devolve o modelo escolhido, ou None."""
        dialogo = cls(parent)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialogo.chosen
