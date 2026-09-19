"""Ícone na bandeja do Windows (área de notificação).

Usa o ``QSystemTrayIcon`` do próprio Qt, e não a biblioteca ``pystray``: o
pystray roda em thread própria e, combinado com o laço de eventos do Qt, é uma
fonte conhecida de travamento no encerramento. Como o Qt já tem bandeja nativa
e integrada, não há motivo para misturar os dois.

O app não fecha ao clicar no X: ele se esconde aqui. Isso é o comportamento
esperado de um app de bandeja e evita perder abas abertas por engano.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QApplication

from edgemd import APP_NAME

log = logging.getLogger(__name__)

MAX_TRAY_RECENT = 8


class TrayIcon(QObject):
    """Bandeja com menu de acesso rápido."""

    showRequested = pyqtSignal()
    hideRequested = pyqtSignal()
    newFileRequested = pyqtSignal()
    openFileRequested = pyqtSignal()
    openFolderRequested = pyqtSignal()
    settingsRequested = pyqtSignal()
    fileRequested = pyqtSignal(str)
    quitRequested = pyqtSignal()

    def __init__(self, icon, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._normal_icon = icon
        self._dirty_icon = None

        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip(APP_NAME)
        self._tray.activated.connect(self._on_activated)

        self._menu = QMenu()

        self._show_action = QAction("Mostrar janela", self._menu)
        self._show_action.triggered.connect(self.showRequested)
        self._menu.addAction(self._show_action)

        self._hide_action = QAction("Ocultar janela", self._menu)
        self._hide_action.triggered.connect(self.hideRequested)
        self._menu.addAction(self._hide_action)

        self._menu.addSeparator()

        new_action = QAction("Novo arquivo", self._menu)
        new_action.triggered.connect(self.newFileRequested)
        self._menu.addAction(new_action)

        open_action = QAction("Abrir arquivo…", self._menu)
        open_action.triggered.connect(self.openFileRequested)
        self._menu.addAction(open_action)

        folder_action = QAction("Abrir pasta…", self._menu)
        folder_action.triggered.connect(self.openFolderRequested)
        self._menu.addAction(folder_action)

        self._menu.addSeparator()
        self._recent_menu = self._menu.addMenu("Recentes")
        self._recent_menu.setEnabled(False)

        self._menu.addSeparator()
        settings_action = QAction("Preferências…", self._menu)
        settings_action.triggered.connect(self.settingsRequested)
        self._menu.addAction(settings_action)

        self._menu.addSeparator()
        quit_action = QAction("Sair", self._menu)
        quit_action.triggered.connect(self.quitRequested)
        self._menu.addAction(quit_action)

        self._tray.setContextMenu(self._menu)

    # ------------------------------------------------------------------
    # Disponibilidade
    # ------------------------------------------------------------------
    @staticmethod
    def is_available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self) -> None:
        if self.is_available():
            self._tray.show()

    def hide(self) -> None:
        self._tray.hide()

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------
    def set_icons(self, normal, dirty) -> None:
        """Guarda os dois ícones; :meth:`set_dirty` alterna entre eles."""
        self._normal_icon = normal
        self._dirty_icon = dirty

    def set_dirty(self, dirty: bool) -> None:
        """Troca o ícone quando há alterações não salvas."""
        if dirty and self._dirty_icon is not None:
            self._tray.setIcon(self._dirty_icon)
        elif self._normal_icon is not None:
            self._tray.setIcon(self._normal_icon)

    def set_tooltip(self, text: str) -> None:
        self._tray.setToolTip(text)

    def update_recent(self, files: list[str]) -> None:
        """Reconstrói o submenu de recentes."""
        self._recent_menu.clear()
        if not files:
            placeholder = QAction("(vazio)", self._recent_menu)
            placeholder.setEnabled(False)
            self._recent_menu.addAction(placeholder)
            self._recent_menu.setEnabled(False)
            return

        for path in files[:MAX_TRAY_RECENT]:
            action = QAction(path, self._recent_menu)
            action.setToolTip(path)
            action.triggered.connect(lambda _checked=False, p=path: self.fileRequested.emit(p))
            self._recent_menu.addAction(action)
        self._recent_menu.setEnabled(True)

    # ------------------------------------------------------------------
    # Notificações
    # ------------------------------------------------------------------
    def notify(self, title: str, message: str) -> None:
        """Mostra um balão da bandeja, se o sistema suportar."""
        if not self.is_available():
            return
        if not QSystemTrayIcon.supportsMessages():
            return
        self._tray.showMessage(
            title, message, QSystemTrayIcon.MessageIcon.Information, 3500
        )

    # ------------------------------------------------------------------
    # Eventos
    # ------------------------------------------------------------------
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.showRequested.emit()


def clipboard_has_files() -> list[str]:
    """Arquivos atualmente no clipboard, se houver.

    Usado pelo menu da bandeja para "abrir o que foi copiado". Lê ``CF_HDROP``
    via ``QMimeData``, que o Qt já decodifica para nós.
    """
    mime = QApplication.clipboard().mimeData()
    if mime is None or not mime.hasUrls():
        return []
    return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
