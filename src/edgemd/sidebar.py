"""Painel lateral com a árvore de arquivos Markdown de uma pasta.

Um detalhe que costuma passar batido: ``QFileSystemModel.setNameFilters()``
aplica o filtro **também a diretórios**. Filtrar por ``*.md`` ali esconderia
todas as subpastas e a árvore ficaria inavegável. Por isso o filtro é feito por
um ``QSortFilterProxyModel`` que aceita qualquer diretório e aplica o padrão
somente a arquivos.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import (
    QDir,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    QUrl,
    pyqtSignal,
)
# QFileSystemModel vive em QtGui no Qt 6 (em Qt 5 ficava em QtWidgets).
from PyQt6.QtGui import QAction, QDesktopServices, QFileSystemModel
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from edgemd.editor_tab import MARKDOWN_SUFFIXES
from edgemd.shell import move_to_trash, reveal_in_file_manager, trash_name

log = logging.getLogger(__name__)

#: Sufixos considerados navegáveis na árvore.
VISIBLE_SUFFIXES = set(MARKDOWN_SUFFIXES) | {".json", ".yaml", ".yml", ".csv"}


class MarkdownFilterProxy(QSortFilterProxyModel):
    """Filtra arquivos por sufixo/nome, mantendo todas as pastas visíveis."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._needle = ""
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_needle(self, text: str) -> None:
        """Texto de busca; vazio volta a mostrar todos os arquivos suportados."""
        self._needle = text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(  # noqa: N802 - assinatura do Qt
        self, source_row: int, source_parent: QModelIndex
    ) -> bool:
        model = self.sourceModel()
        if model is None:
            return True

        index = model.index(source_row, 0, source_parent)
        # Pastas sempre passam: senão a busca esconderia o caminho até o arquivo.
        if model.isDir(index):
            return True

        name = model.fileName(index)
        suffix = Path(name).suffix.lower()

        if self._needle:
            # Com busca ativa, aceita qualquer arquivo cujo nome case, para não
            # frustrar quem procura por um .pdf dentro da pasta de notas.
            return self._needle in name.lower()

        return suffix in VISIBLE_SUFFIXES


class FileTree(QTreeView):
    """Árvore de arquivos com menu de contexto."""

    fileActivated = pyqtSignal(str)
    newFileRequested = pyqtSignal(str)   # diretório
    newFolderRequested = pyqtSignal(str)  # diretório
    renameRequested = pyqtSignal(str)    # caminho
    deleteRequested = pyqtSignal(str)    # caminho
    revealRequested = pyqtSignal(str)    # caminho

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setAnimated(True)
        self.setUniformRowHeights(True)
        self.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.activated.connect(self._on_activated)

    def _source_path(self, index: QModelIndex) -> str | None:
        if not index.isValid():
            return None
        proxy = self.model()
        if isinstance(proxy, QSortFilterProxyModel):
            index = proxy.mapToSource(index)
        model = proxy.sourceModel() if isinstance(proxy, QSortFilterProxyModel) else proxy
        if not isinstance(model, QFileSystemModel):
            return None
        return model.filePath(index)

    def _on_activated(self, index: QModelIndex) -> None:
        # Enter/duplo-clique: pasta expande, arquivo abre.
        path = self._source_path(index)
        if path and Path(path).is_file():
            self.fileActivated.emit(path)

    def _on_context_menu(self, position) -> None:
        index = self.indexAt(position)
        path = self._source_path(index)
        directory = path if path and Path(path).is_dir() else (
            str(Path(path).parent) if path else self._root_directory()
        )
        if not directory:
            return

        menu = QMenu(self)

        if path and Path(path).is_file():
            open_action = QAction("Abrir", self)
            open_action.triggered.connect(lambda: self.fileActivated.emit(path))
            menu.addAction(open_action)
            menu.addSeparator()

        new_file = QAction("Novo arquivo Markdown…", self)
        new_file.triggered.connect(lambda: self.newFileRequested.emit(directory))
        menu.addAction(new_file)

        new_folder = QAction("Nova pasta…", self)
        new_folder.triggered.connect(lambda: self.newFolderRequested.emit(directory))
        menu.addAction(new_folder)

        if path:
            menu.addSeparator()

            rename = QAction("Renomear…", self)
            rename.triggered.connect(lambda: self.renameRequested.emit(path))
            menu.addAction(rename)

            reveal = QAction("Mostrar no Explorer", self)
            reveal.triggered.connect(lambda: self.revealRequested.emit(path))
            menu.addAction(reveal)

            copy_path = QAction("Copiar caminho", self)
            copy_path.triggered.connect(lambda: self._copy_path(path))
            menu.addAction(copy_path)

            menu.addSeparator()
            delete = QAction("Excluir…", self)
            delete.triggered.connect(lambda: self.deleteRequested.emit(path))
            menu.addAction(delete)

        menu.exec(self.viewport().mapToGlobal(position))

    def _copy_path(self, path: str) -> None:
        QApplication.clipboard().setText(path)

    def _root_directory(self) -> str | None:
        model = self.model()
        if isinstance(model, QSortFilterProxyModel):
            model = model.sourceModel()
        if isinstance(model, QFileSystemModel):
            root = model.rootPath()
            return root or None
        return None


class Sidebar(QWidget):
    """Painel lateral: cabeçalho, busca e árvore de arquivos."""

    fileActivated = pyqtSignal(str)
    folderOpened = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._root: Path | None = None

        self._model = QFileSystemModel(self)
        # Não usamos setNameFilters aqui de propósito (ver docstring do módulo):
        # o filtro vive no proxy.
        self._model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self._model.setReadOnly(False)

        self._proxy = MarkdownFilterProxy(self)
        self._proxy.setSourceModel(self._model)

        self._tree = FileTree(self)
        self._tree.setModel(self._proxy)
        self._tree.fileActivated.connect(self.fileActivated)
        self._tree.newFileRequested.connect(self._on_new_file)
        self._tree.newFolderRequested.connect(self._on_new_folder)
        self._tree.renameRequested.connect(self._on_rename)
        self._tree.deleteRequested.connect(self._on_delete)
        self._tree.revealRequested.connect(self.reveal_in_explorer)
        self._tree.doubleClicked.connect(self._on_double_clicked)

        # --- cabeçalho -------------------------------------------------
        self._title = QLabel("Nenhuma pasta aberta")
        self._title.setObjectName("sidebarTitle")
        self._title.setWordWrap(False)
        self._title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._open_button = QToolButton()
        self._open_button.setText("Abrir pasta")
        self._open_button.setToolTip("Escolher a pasta de notas")
        self._open_button.clicked.connect(self.pick_folder)

        self._collapse_button = QToolButton()
        self._collapse_button.setText("⌄")
        self._collapse_button.setToolTip("Recolher tudo")
        self._collapse_button.clicked.connect(self._tree.collapseAll)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self._title, 1)
        header.addWidget(self._collapse_button)
        header.addWidget(self._open_button)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filtrar arquivos…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._proxy.set_needle)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 4, 8)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self._search)
        layout.addWidget(self._tree, 1)

    # ------------------------------------------------------------------
    # Pasta raiz
    # ------------------------------------------------------------------
    @property
    def root(self) -> Path | None:
        return self._root

    def set_root(self, folder: str | Path) -> bool:
        """Define a pasta exibida na árvore."""
        path = Path(folder).resolve()
        if not path.is_dir():
            log.warning("Pasta inválida para a sidebar: %s", path)
            return False

        self._root = path
        self._model.setRootPath(str(path))
        self._tree.setRootIndex(self._proxy.mapFromSource(self._model.index(str(path))))
        self._tree.setColumnHidden(1, True)
        self._tree.setColumnHidden(2, True)
        self._tree.setColumnHidden(3, True)
        self._title.setText(path.name or str(path))
        self._title.setToolTip(str(path))
        self.folderOpened.emit(str(path))
        return True

    def pick_folder(self) -> None:
        start = str(self._root) if self._root else str(Path.home())
        folder = QFileDialog.getExistingDirectory(
            self, "Escolher pasta de notas", start
        )
        if folder:
            self.set_root(folder)

    def refresh(self) -> None:
        if self._root:
            self._model.setRootPath("")
            self._model.setRootPath(str(self._root))

    def reveal_in_explorer(self, path: str) -> None:
        """Mostra o arquivo no gerenciador de pastas do sistema."""
        if not reveal_in_file_manager(path):
            log.warning("Não foi possível mostrar %s no gerenciador de pastas.", path)

    def select_path(self, path: str | Path) -> None:
        """Seleciona um arquivo na árvore, se ele estiver dentro da raiz."""
        if self._root is None:
            return
        target = Path(path).resolve()
        try:
            target.relative_to(self._root)
        except ValueError:
            return  # fora da pasta aberta
        index = self._proxy.mapFromSource(self._model.index(str(target)))
        if index.isValid():
            self._tree.setCurrentIndex(index)
            self._tree.scrollTo(index, QTreeView.ScrollHint.PositionAtCenter)

    # ------------------------------------------------------------------
    # Ações de arquivo
    # ------------------------------------------------------------------
    def _on_double_clicked(self, index: QModelIndex) -> None:
        path = self._tree._source_path(index)
        if path and Path(path).is_file():
            self.fileActivated.emit(path)

    def _on_new_file(self, directory: str) -> None:
        name, ok = QInputDialog.getText(
            self, "Novo arquivo", "Nome do arquivo:", text="nota.md"
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        if not Path(name).suffix:
            name += ".md"

        target = Path(directory) / name
        if target.exists():
            QMessageBox.warning(
                self, "Já existe", f"O arquivo já existe:\n{target}"
            )
            return
        try:
            target.write_text(f"# {target.stem}\n\n", encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(
                self, "Não foi possível criar", f"{target}\n\n{exc}"
            )
            return
        self.fileActivated.emit(str(target))

    def _on_new_folder(self, directory: str) -> None:
        name, ok = QInputDialog.getText(self, "Nova pasta", "Nome da pasta:")
        if not ok or not name.strip():
            return
        target = Path(directory) / name.strip()
        try:
            target.mkdir(parents=False, exist_ok=False)
        except OSError as exc:
            QMessageBox.critical(
                self, "Não foi possível criar", f"{target}\n\n{exc}"
            )

    def _on_rename(self, path: str) -> None:
        source = Path(path)
        new_name, ok = QInputDialog.getText(
            self, "Renomear", "Novo nome:", text=source.name
        )
        if not ok or not new_name.strip() or new_name.strip() == source.name:
            return
        target = source.parent / new_name.strip()
        try:
            source.rename(target)
        except OSError as exc:
            QMessageBox.critical(
                self, "Não foi possível renomear", f"{source}\n\n{exc}"
            )

    def _on_delete(self, path: str) -> None:
        target = Path(path)
        answer = QMessageBox.question(
            self,
            "Excluir",
            f"Excluir definitivamente?\\n\\n{target}\\n\\n"
            f"O arquivo vai para a {trash_name()} do sistema.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            move_to_trash(target)
        except OSError as exc:
            QMessageBox.critical(
                self, "Não foi possível excluir", f"{target}\n\n{exc}"
            )

    @staticmethod
    def _send_to_trash(target: Path) -> None:
        """Compatibilidade: a implementação vive em :mod:`edgemd.shell`.

        Mantido como delegação para não quebrar quem já chamava este nome; a
        lógica por plataforma (PowerShell no Windows, ``gio`` no Linux,
        AppleScript no macOS) está toda em ``shell.move_to_trash``.
        """
        move_to_trash(target)
