"""Uma aba = um documento: caminho, encoding, estado sujo e o editor.

A escrita em disco é deliberadamente cuidadosa, porque um editor que corrompe
o arquivo do usuário num crash é pior do que não existir:

1. grava num arquivo temporário **na mesma pasta** do destino (mesmo volume,
   então ``os.replace`` é atômico);
2. preserva o encoding e o fim de linha originais do arquivo;
3. só então substitui o original, com ``os.replace``.

Guardamos também o ``mtime`` e o tamanho originais, para detectar edição
externa (o usuário salvou o mesmo arquivo em outro programa).
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from edgemd.editor_widget import MarkdownEditor
from edgemd.render import read_text_file

log = logging.getLogger(__name__)

#: Extensões que o app trata como Markdown.
MARKDOWN_SUFFIXES = (".md", ".markdown", ".mdown", ".mkd", ".mkdn", ".mdx", ".txt")

#: Extensões que o diálogo de salvar sugere.
FILE_FILTER = "Markdown (*.md *.markdown *.mdown *.mkd *.mkdn *.mdx);;Texto (*.txt);;Todos os arquivos (*)"

DEFAULT_ENCODING = "utf-8"
DEFAULT_EOL = "\r\n"


class EditorTab(QWidget):
    """Documento editável, com o editor Markdown embutido."""

    dirtyChanged = pyqtSignal(bool)
    titleChanged = pyqtSignal(str)
    #: Texto mudou — o MainWindow usa para agendar o re-render do preview.
    contentsChanged = pyqtSignal()
    #: Linha do cursor mudou (1-based).
    cursorLineChanged = pyqtSignal(int)
    #: Estado de undo/redo mudou (habilita as ações do menu).
    undoAvailableChanged = pyqtSignal(bool)
    redoAvailableChanged = pyqtSignal(bool)
    #: O arquivo mudou no disco por fora do app.
    externallyModified = pyqtSignal()

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.path: Path | None = Path(path).resolve() if path else None
        self.encoding: str = DEFAULT_ENCODING
        self.eol: str = DEFAULT_EOL
        self._dirty = False
        self._disk_signature: tuple[float, int] | None = None
        self._untitled_label = "Sem título"
        #: Evita empilhar caixas de diálogo enquanto uma já está aberta para
        #: este documento (a verificação de disco roda a cada poucos segundos).
        self.external_prompt_open = False
        #: Posição de leitura guardada ao trocar de aba.
        self.last_preview_line = 1
        self.last_editor_line = 1

        self.editor = MarkdownEditor(theme=theme, parent=self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.editor)

        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.cursorLineChanged.connect(self._on_cursor_line)
        self.editor.undoAvailable.connect(self.undoAvailableChanged)
        self.editor.redoAvailable.connect(self.redoAvailableChanged)

        if self.path is not None:
            if not self.load(self.path):
                # load() já registrou o motivo; deixamos o documento vazio para
                # que o usuário ainda possa editar e salvar em outro lugar.
                self.path = None
        else:
            self._dirty = False
            self._mark_clean()

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------
    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def display_name(self) -> str:
        """Nome curto para a aba, com marcador de alteração."""
        base = self.path.name if self.path else self._untitled_label
        return f"{base} •" if self._dirty else base

    @property
    def absolute_title(self) -> str:
        return str(self.path) if self.path else self._untitled_label

    def set_untitled_label(self, label: str) -> None:
        """Define o rótulo de um documento ainda sem arquivo.

        O MainWindow escolhe o número ("Sem título", "Sem título 2", ...) para
        que os rótulos não se repitam entre abas.
        """
        self._untitled_label = label
        self.titleChanged.emit(self.display_name)

    def _on_text_changed(self) -> None:
        if not self._dirty:
            self._dirty = True
            self.dirtyChanged.emit(True)
            self.titleChanged.emit(self.display_name)
        self.contentsChanged.emit()

    def _on_cursor_line(self, line: int) -> None:
        self.last_editor_line = line
        self.cursorLineChanged.emit(line)

    def _mark_clean(self) -> None:
        if self._dirty:
            self._dirty = False
            self.dirtyChanged.emit(False)
        self.titleChanged.emit(self.display_name)
        self.editor.document().setModified(False)
        self._record_disk_signature()

    # ------------------------------------------------------------------
    # Leitura
    # ------------------------------------------------------------------
    def load(self, path: str | Path) -> bool:
        """Carrega um arquivo. Devolve False (sem exceção) em caso de falha."""
        target = Path(path).resolve()
        try:
            text, encoding, eol = read_text_file(target)
        except OSError as exc:
            log.error("Não foi possível ler %s: %s", target, exc)
            return False

        self.path = target
        self.encoding = encoding
        self.eol = eol

        # Desliga o rastreio de alteração enquanto inserimos o conteúdo, senão
        # o documento nasceria "sujo".
        self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor.blockSignals(False)

        self._dirty = False
        self._mark_clean()
        self.editor.document().setModified(False)
        self.titleChanged.emit(self.display_name)
        return True

    def reload(self) -> bool:
        """Recarrega do disco, descartando alterações locais."""
        if self.path is None:
            return False
        return self.load(self.path)

    # ------------------------------------------------------------------
    # Escrita
    # ------------------------------------------------------------------
    def save_as(self, path: str | Path) -> bool:
        """Salva num caminho novo e passa a apontar para ele."""
        self.path = Path(path).resolve()
        # Um arquivo novo adota os padrões do app, não os do anterior.
        if self.encoding not in ("utf-8", "utf-8-sig"):
            self.encoding = DEFAULT_ENCODING
        return self.save()

    def save(self) -> bool:
        """Grava o conteúdo no disco. True em caso de sucesso."""
        if self.path is None:
            return False

        text = self.editor.toPlainText()
        # Normaliza para o EOL do arquivo: o Qt entrega sempre "\n".
        payload_text = text.replace("\r\n", "\n").replace("\r", "\n")
        if self.eol != "\n":
            payload_text = payload_text.replace("\n", self.eol)

        encoding = self.encoding or DEFAULT_ENCODING
        try:
            payload = payload_text.encode(encoding)
        except UnicodeEncodeError:
            # Arquivo nasceu cp1252 e o usuário digitou algo fora dele (emoji,
            # por exemplo). Promovemos para UTF-8 em vez de falhar o salvamento.
            log.warning(
                "Conteúdo não cabe em %s; salvando como utf-8.", encoding
            )
            encoding = "utf-8"
            self.encoding = encoding
            payload = payload_text.encode(encoding)

        if not self._atomic_write(self.path, payload):
            return False

        self._mark_clean()
        return True

    @staticmethod
    def _atomic_write(target: Path, payload: bytes) -> bool:
        """Grava via temporário + os.replace, preservando permissões."""
        directory = target.parent
        handle = None
        temp_path: str | None = None
        try:
            fd, temp_path = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=str(directory)
            )
            handle = os.fdopen(fd, "wb")
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            handle = None

            # Preserva as permissões do arquivo original, quando ele existe.
            if target.exists():
                try:
                    os.chmod(temp_path, os.stat(target).st_mode)
                except OSError:
                    pass

            os.replace(temp_path, target)
            return True
        except OSError as exc:
            log.error("Falha ao gravar %s: %s", target, exc)
            if handle is not None:
                handle.close()
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            return False

    # ------------------------------------------------------------------
    # Alteração externa
    # ------------------------------------------------------------------
    def record_disk_signature(self) -> None:
        """Realinha a assinatura de disco com o estado atual do arquivo.

        Usado quando o usuário decide manter o conteúdo do editor depois de
        uma alteração externa: sem isso a verificação periódica voltaria a
        perguntar a cada poucos segundos.
        """
        self._record_disk_signature()

    def _record_disk_signature(self) -> None:
        if self.path is None:
            self._disk_signature = None
            return
        try:
            stat = self.path.stat()
            self._disk_signature = (stat.st_mtime, stat.st_size)
        except OSError:
            self._disk_signature = None

    def check_external_change(self) -> bool:
        """True se o arquivo mudou no disco desde o último carregamento/salvamento."""
        if self.path is None or self._disk_signature is None:
            return False
        try:
            stat = self.path.stat()
        except OSError:
            # Arquivo sumiu: tratamos como alteração para avisar o usuário.
            return True
        current = (stat.st_mtime, stat.st_size)
        changed = current != self._disk_signature
        if changed:
            self.externallyModified.emit()
        return changed

    # ------------------------------------------------------------------
    # Utilitários
    # ------------------------------------------------------------------
    def statistics(self) -> dict[str, int]:
        """Números mostrados na barra de status."""
        text = self.editor.toPlainText()
        words = len([w for w in text.split() if w.strip()])
        return {
            "lines": self.editor.blockCount(),
            "words": words,
            "characters": len(text),
        }

    def modified_at(self) -> str | None:
        if self.path is None or not self.path.exists():
            return None
        try:
            return datetime.fromtimestamp(self.path.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
        except OSError:
            return None
