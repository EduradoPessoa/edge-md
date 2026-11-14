"""Interface da atualização e do rollback.

A lógica mora em ``updater``; aqui ficam só os diálogos e as threads que impedem
a rede de travar a janela.
"""

from __future__ import annotations

import logging
import os
import time
import webbrowser
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from edgemd import APP_NAME, __version__, updater
from edgemd.updater import Cancelled, Release, UpdateError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------
class _FetchThread(QThread):
    done = pyqtSignal(list)
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            self.done.emit(updater.fetch_releases())
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - uma thread não pode derrubar o app
            log.exception("Falha inesperada ao consultar versões")
            self.failed.emit(str(exc))


class _DownloadThread(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, release: Release, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._release = release
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            path = updater.download_installer(
                self._release,
                progress=lambda got, total: self.progress.emit(got, total),
                cancelled=lambda: self._cancel,
            )
            self.done.emit(str(path))
        except Cancelled:
            self.failed.emit("")
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("Falha inesperada no download")
            self.failed.emit(str(exc))


# ---------------------------------------------------------------------------
# Diálogos
# ---------------------------------------------------------------------------
class UpdateDialog(QDialog):
    """Mostra a versão nova e as notas, e pergunta o que fazer."""

    INSTALL, LATER, SKIP, OPEN_PAGE = range(4)

    def __init__(self, release: Release, can_install: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.choice = self.LATER
        self.setWindowTitle(f"{APP_NAME} — atualização disponível")
        self.resize(560, 460)

        layout = QVBoxLayout(self)
        titulo = QLabel(f"<h3>EdgeMD {release.version} disponível</h3>"
                        f"<p>Você está na versão {__version__}.</p>")
        layout.addWidget(titulo)

        notas = QTextBrowser()
        notas.setOpenExternalLinks(True)
        notas.setMarkdown(release.body or "_Sem notas para esta versão._")
        layout.addWidget(notas, 1)

        if can_install:
            aviso = "O instalador é baixado e conferido pelo SHA-256 antes de rodar. O EdgeMD fecha e reabre sozinho."
        else:
            aviso = "Esta instalação não se atualiza sozinha. A página da versão abre no navegador."
        info = QLabel(aviso)
        info.setWordWrap(True)
        layout.addWidget(info)

        botoes = QHBoxLayout()
        principal = QPushButton("Baixar e instalar" if can_install else "Abrir página da versão")
        principal.setDefault(True)
        principal.clicked.connect(lambda: self._done(self.INSTALL if can_install else self.OPEN_PAGE))
        depois = QPushButton("Lembrar depois")
        depois.clicked.connect(lambda: self._done(self.LATER))
        pular = QPushButton("Ignorar esta versão")
        pular.clicked.connect(lambda: self._done(self.SKIP))
        botoes.addWidget(pular)
        botoes.addStretch(1)
        botoes.addWidget(depois)
        botoes.addWidget(principal)
        layout.addLayout(botoes)

    def _done(self, choice: int) -> None:
        self.choice = choice
        self.accept()


class VersionsDialog(QDialog):
    """Lista as versões publicadas e permite instalar qualquer uma (rollback)."""

    def __init__(self, releases: list[Release], can_install: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.selected: Release | None = None
        self.releases = releases
        self.setWindowTitle(f"{APP_NAME} — versões")
        self.resize(560, 380)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"Versão em uso: <b>{__version__}</b>. Escolha uma para instalar — "
            "inclusive uma anterior, se a atual deu problema."
        ))

        self.table = QTableWidget(len(releases), 3)
        self.table.setHorizontalHeaderLabels(["Versão", "Publicada em", "Situação"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        for row, rel in enumerate(releases):
            self.table.setItem(row, 0, QTableWidgetItem(rel.version))
            self.table.setItem(row, 1, QTableWidgetItem(rel.date))
            self.table.setItem(row, 2, QTableWidgetItem(self.situacao(rel, can_install)))
        self.table.currentCellChanged.connect(lambda *_: self._sync_buttons())
        layout.addWidget(self.table, 1)

        self._can_install = can_install
        botoes = QDialogButtonBox()
        self.install_btn = botoes.addButton("Instalar esta versão", QDialogButtonBox.ButtonRole.AcceptRole)
        self.page_btn = botoes.addButton("Ver no GitHub", QDialogButtonBox.ButtonRole.ActionRole)
        botoes.addButton("Fechar", QDialogButtonBox.ButtonRole.RejectRole)
        self.install_btn.clicked.connect(self._install)
        self.page_btn.clicked.connect(self._open_page)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)

        if releases:
            self.table.selectRow(0)
        self._sync_buttons()

    @staticmethod
    def situacao(rel: Release, can_install: bool) -> str:
        if rel.version == __version__:
            estado = "em uso"
        elif updater.is_newer(rel.version, __version__):
            estado = "mais nova"
        else:
            estado = "anterior"
        if rel.version != __version__ and updater.cached_installer(rel):
            estado += " · no cache (offline)"
        if not rel.installable:
            estado += " · sem instalador para Windows"
        return estado

    def _current(self) -> Release | None:
        row = self.table.currentRow()
        return self.releases[row] if 0 <= row < len(self.releases) else None

    def _sync_buttons(self) -> None:
        rel = self._current()
        self.install_btn.setEnabled(
            bool(rel and self._can_install and rel.installable and rel.version != __version__)
        )
        self.page_btn.setEnabled(rel is not None)

    def _install(self) -> None:
        self.selected = self._current()
        self.accept()

    def _open_page(self) -> None:
        rel = self._current()
        if rel:
            webbrowser.open(rel.html_url)


# ---------------------------------------------------------------------------
# Controlador
# ---------------------------------------------------------------------------
class UpdateController(QObject):
    """Orquestra checagem, aviso, download, instalação e rollback."""

    def __init__(self, window, config) -> None:
        super().__init__(window)
        self._window = window
        self._config = config
        self._fetch: _FetchThread | None = None
        self._download: _DownloadThread | None = None
        self._progress: QProgressDialog | None = None

    # -- entradas ---------------------------------------------------------
    def check_on_startup(self) -> None:
        """Checagem silenciosa ao abrir: só aparece algo se houver versão nova."""
        if os.environ.get("EDGEMD_NO_UPDATE_CHECK") or not self._config.update_check_enabled:
            return
        if not updater.should_check(self._config.update_last_check):
            return
        self._start_fetch(manual=False)

    def check_now(self) -> None:
        self._start_fetch(manual=True)

    def show_versions(self) -> None:
        self._start_fetch(manual=True, then_versions=True)

    # -- consulta ---------------------------------------------------------
    def _start_fetch(self, *, manual: bool, then_versions: bool = False) -> None:
        if self._fetch is not None and self._fetch.isRunning():
            return
        self._fetch = _FetchThread(self)
        self._fetch.done.connect(lambda rels: self._on_fetched(rels, manual, then_versions))
        self._fetch.failed.connect(lambda msg: self._on_fetch_failed(msg, manual))
        self._fetch.start()
        if manual:
            self._window.statusBar().showMessage("Consultando versões…", 4000)

    def _on_fetch_failed(self, message: str, manual: bool) -> None:
        log.info("Checagem de atualização falhou: %s", message)
        if manual:
            QMessageBox.warning(self._window, "Atualizações", message or "Não foi possível consultar o GitHub.")

    def _on_fetched(self, releases: list[Release], manual: bool, then_versions: bool) -> None:
        self._config.update_last_check = time.time()
        self._config.sync()
        can_install = updater.can_self_install()

        if then_versions:
            if not releases:
                QMessageBox.information(self._window, "Versões", "Nenhuma versão publicada foi encontrada.")
                return
            dialog = VersionsDialog(releases, can_install, self._window)
            if dialog.exec() and dialog.selected is not None:
                self._install(dialog.selected)
            return

        update = updater.newest_update(releases)
        if update is None:
            if manual:
                QMessageBox.information(
                    self._window, "Atualizações", f"Você já está na versão mais recente ({__version__})."
                )
            return
        if not manual and update.version == self._config.update_skipped_version:
            return

        dialog = UpdateDialog(update, can_install and update.installable, self._window)
        dialog.exec()
        if dialog.choice == UpdateDialog.INSTALL:
            self._install(update)
        elif dialog.choice == UpdateDialog.OPEN_PAGE:
            webbrowser.open(update.html_url)
        elif dialog.choice == UpdateDialog.SKIP:
            self._config.update_skipped_version = update.version
            self._config.sync()

    # -- instalação / rollback -------------------------------------------
    def _install(self, release: Release) -> None:
        if not (updater.can_self_install() and release.installable):
            webbrowser.open(release.html_url)
            return

        voltando = updater.is_newer(__version__, release.version)
        if voltando:
            resposta = QMessageBox.question(
                self._window,
                "Voltar para uma versão anterior",
                f"Instalar a versão {release.version}, anterior à atual ({__version__})?\n\n"
                "Seus arquivos e preferências são mantidos. O app não vai avisar "
                f"da versão {__version__} de novo.",
            )
            if resposta != QMessageBox.StandardButton.Yes:
                return

        self._progress = QProgressDialog(
            f"Baixando o EdgeMD {release.version}…", "Cancelar", 0, 100, self._window
        )
        self._progress.setWindowTitle("Atualização")
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setValue(0)

        self._download = _DownloadThread(release, self)
        self._download.progress.connect(self._on_progress)
        self._download.done.connect(lambda path: self._on_downloaded(release, Path(path), voltando))
        self._download.failed.connect(self._on_download_failed)
        self._progress.canceled.connect(self._download.cancel)
        self._download.start()

    def _on_progress(self, got: int, total: int) -> None:
        if self._progress is not None and total:
            self._progress.setValue(min(99, int(got * 100 / total)))

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.canceled.disconnect()
            self._progress.close()
            self._progress = None

    def _on_download_failed(self, message: str) -> None:
        self._close_progress()
        if message:  # vazio = cancelado pelo usuário
            QMessageBox.critical(self._window, "Atualização", message)

    def _on_downloaded(self, release: Release, path: Path, voltando: bool) -> None:
        self._close_progress()
        resposta = QMessageBox.question(
            self._window,
            "Pronto para instalar",
            f"O EdgeMD {release.version} foi baixado e conferido (SHA-256).\n\n"
            "O app vai fechar e reabrir sozinho. Continuar?",
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return

        # Passa pela confirmação de documentos não salvos; se o usuário desistir
        # ali, _force_close fica falso e nada é instalado.
        self._window.quit_application()
        if not getattr(self._window, "_force_close", False):
            return

        if voltando:
            # Sem isto, a próxima abertura voltaria a oferecer a versão que o
            # usuário acabou de abandonar.
            self._config.update_skipped_version = __version__
            self._config.sync()
        try:
            updater.prune_cache([release.version, __version__])
            updater.launch_installer(path)
        except (UpdateError, OSError) as exc:
            log.exception("Não foi possível iniciar o instalador")
            QMessageBox.critical(None, "Atualização", f"Não foi possível iniciar o instalador:\n{exc}")
