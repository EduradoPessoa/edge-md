"""Preview do Markdown, hospedado num QWebEngineView (Chromium).

**Uma única instância é compartilhada por todas as abas.** Cada
``QWebEngineView`` carrega um compositor e um conjunto de web contents
próprios; um por aba faria o consumo de memória crescer rápido demais a partir
de umas dez abas abertas. Como só uma aba é visível por vez, o ``MainWindow``
tem um preview só e troca o conteúdo ao mudar de aba. A posição de leitura de
cada aba é guardada no próprio documento e restaurada na volta.

Três detalhes de integração que valem explicação:

* **``setHtml`` tem limite de tamanho.** O Qt rejeita (silenciosamente) HTML
  acima de ~2 MB. Para documentos grandes caímos para um arquivo temporário
  carregado por ``file://``, que não tem esse limite.
* **``baseUrl`` é a pasta do .md.** É o que faz imagens relativas aparecerem.
* **A ponte JS<->Python usa QWebChannel.** O ``qwebchannel.js`` vem dos
  recursos do próprio Qt (``qrc:///``), então não precisa ser vendorizado.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

from edgemd.render import RenderedDocument

log = logging.getLogger(__name__)

#: Acima disto usamos arquivo temporário em vez de setHtml.
SETHTML_LIMIT_BYTES = 1_500_000

#: Cores de fundo por tema, para evitar o flash branco ao (re)carregar.
BACKGROUND = {"dark": "#16181d", "light": "#fdfdfc"}


class PreviewBridge(QObject):
    """Objeto exposto ao JavaScript do preview.

    Os nomes dos slots são o contrato com ``preview.js``: ``onScrolled``,
    ``onLinkActivated`` e ``onReady``. Nenhum deles pode se chamar igual ao
    sinal correspondente — em Python o método sobrescreveria o atributo do
    sinal em silêncio, e o ``connect`` falharia com "function has no attribute
    connect".
    """

    scrolled = pyqtSignal(int)
    linkActivated = pyqtSignal(str)
    ready = pyqtSignal()
    editRequested = pyqtSignal()

    @pyqtSlot(int)
    def onScrolled(self, line: int) -> None:
        self.scrolled.emit(int(line))

    @pyqtSlot(str)
    def onLinkActivated(self, url: str) -> None:
        self.linkActivated.emit(url)

    @pyqtSlot()
    def onReady(self) -> None:
        self.ready.emit()

    @pyqtSlot()
    def onEditRequested(self) -> None:
        self.editRequested.emit()


class PreviewPage(QWebEnginePage):
    """Página que decide o destino dos cliques em links."""

    #: Emitido quando o link aponta para um arquivo que o app deve abrir.
    fileRequested = pyqtSignal(str)
    #: Emitido para links externos que devem ir ao navegador padrão.
    externalRequested = pyqtSignal(str)

    def acceptNavigationRequest(  # noqa: N802 - assinatura do Qt
        self, url: QUrl, nav_type: QWebEnginePage.NavigationType, is_main_frame: bool
    ) -> bool:
        # A carga inicial (setHtml/load) precisa passar.
        if nav_type != QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            return True

        scheme = url.scheme().lower()

        if scheme in ("http", "https", "mailto"):
            self.externalRequested.emit(url.toString())
            return False

        if scheme == "file":
            path = Path(url.toLocalFile())
            # Âncora interna no mesmo arquivo (outro.md#secao) chega aqui com
            # o caminho do documento atual; nesse caso deixamos o Chromium
            # cuidar da rolagem.
            if path.suffix.lower() in (".md", ".markdown", ".mdown", ".mkd", ".txt"):
                self.fileRequested.emit(str(path))
                return False
            self.externalRequested.emit(url.toString())
            return False

        # Qualquer outro esquema (javascript:, data:) é bloqueado: nada no
        # preview legítimo precisa navegar para lá.
        log.debug("Navegação bloqueada para %s", url.toString())
        return False

    def javaScriptConsoleMessage(  # noqa: N802 - assinatura do Qt
        self,
        level: QWebEnginePage.JavaScriptConsoleMessageLevel,
        message: str,
        line_number: int,
        source_id: str,
    ) -> None:
        """Leva os erros de JavaScript para o log do Python.

        Sem isto, uma exceção no ``preview.js`` desaparece sem deixar rastro:
        o preview simplesmente para de responder (sincronia de rolagem, botão
        de copiar) e não há nada indicando o porquê. Avisos e mensagens
        normais ficam em nível de depuração para não poluir.
        """
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            origem = Path(source_id).name if source_id else "preview"
            log.error("Erro de JavaScript em %s:%s — %s", origem, line_number, message)
        else:
            log.debug("JS [%s:%s] %s", source_id, line_number, message)


class PreviewView(QWebEngineView):
    """Visualizador de Markdown renderizado."""

    #: Linha do editor correspondente ao topo do preview.
    scrolled = pyqtSignal(int)
    #: Arquivo local clicado, que o app deve abrir numa aba.
    fileRequested = pyqtSignal(str)
    #: Link externo clicado.
    externalRequested = pyqtSignal(str)
    #: A página terminou de carregar.
    documentLoaded = pyqtSignal()
    #: Duplo clique no documento — pedido para entrar no modo de edição.
    editRequested = pyqtSignal()

    def __init__(self, theme: str = "dark", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._pending_line: int | None = None
        self._temp_file: Path | None = None

        page = PreviewPage(self)
        self.setPage(page)
        page.fileRequested.connect(self.fileRequested)
        page.externalRequested.connect(self.externalRequested)

        self._bridge = PreviewBridge(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self._bridge)
        page.setWebChannel(self._channel)
        self._bridge.scrolled.connect(self.scrolled)
        self._bridge.ready.connect(self._on_bridge_ready)
        self._bridge.linkActivated.connect(self._on_bridge_link)
        self._bridge.editRequested.connect(self.editRequested)

        self._configure_settings()
        self.set_background(theme)
        self.loadFinished.connect(self._on_load_finished)

    # ------------------------------------------------------------------
    # Configuração
    # ------------------------------------------------------------------
    def _configure_settings(self) -> None:
        settings = self.settings()
        # Sem isto o documento não consegue carregar as imagens nem os scripts
        # locais referenciados por file:// — o preview sairia sem estilo.
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled, True
        )

    def set_background(self, theme: str) -> None:
        """Pinta o fundo com a cor do tema, evitando flash branco no recarregar."""
        self.page().setBackgroundColor(QColor(BACKGROUND.get(theme, BACKGROUND["dark"])))

    # ------------------------------------------------------------------
    # Renderização
    # ------------------------------------------------------------------
    def set_document(self, document: RenderedDocument, keep_line: int | None = None) -> None:
        """Exibe um documento renderizado.

        ``keep_line`` restaura a posição de leitura depois da carga — necessário
        porque cada ``setHtml`` recria a página inteira.
        """
        self._pending_line = keep_line

        base_url = (
            QUrl.fromLocalFile(str(document.base_dir) + "/")
            if document.base_dir
            else QUrl("about:blank")
        )

        payload = document.html.encode("utf-8")
        if len(payload) > SETHTML_LIMIT_BYTES:
            # setHtml descarta em silêncio acima de ~2 MB.
            self._load_via_temp_file(document.html, base_url)
        else:
            self.page().setHtml(document.html, base_url)

    def _load_via_temp_file(self, html: str, base_url: QUrl) -> None:
        """Carrega o documento por arquivo temporário, driblando o limite do setHtml.

        O arquivo é escrito na pasta do documento quando possível, para que
        caminhos relativos continuem válidos sem depender do baseUrl.
        """
        self._cleanup_temp_file()
        directory = base_url.toLocalFile() or None
        if directory and not Path(directory).is_dir():
            directory = None

        try:
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".mdpreview.html",
                prefix="edgemd-",
                dir=directory,
                delete=False,
                encoding="utf-8",
            )
        except OSError:
            # Pasta somente-leitura: cai para a pasta temporária do sistema.
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".mdpreview.html",
                prefix="edgemd-",
                delete=False,
                encoding="utf-8",
            )

        with handle:
            handle.write(html)

        self._temp_file = Path(handle.name)
        log.info("Documento grande: carregando por arquivo temporário %s", self._temp_file)
        self.load(QUrl.fromLocalFile(str(self._temp_file)))

    def _cleanup_temp_file(self) -> None:
        if self._temp_file is None:
            return
        try:
            self._temp_file.unlink(missing_ok=True)
        except OSError:
            log.debug("Não foi possível remover o temporário %s", self._temp_file)
        self._temp_file = None

    # ------------------------------------------------------------------
    # Interação
    # ------------------------------------------------------------------
    def apply_theme(self, theme: str) -> None:
        """Troca o tema sem re-renderizar."""
        self._theme = theme
        self.set_background(theme)
        self.page().runJavaScript(f"window.setTheme && window.setTheme({theme!r});")

    def scroll_to_line(self, line: int, smooth: bool = False) -> None:
        """Rola o preview até o bloco correspondente à linha do editor."""
        line = max(1, int(line))
        self.page().runJavaScript(
            f"window.scrollToLine && window.scrollToLine({line}, {str(bool(smooth)).lower()});"
        )

    def refresh(self) -> None:
        """Reprocessa diagramas e matemática sem recarregar a página."""
        self.page().runJavaScript("window.refreshBlocks && window.refreshBlocks();")

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_bridge_ready(self) -> None:
        log.debug("Ponte do preview conectada.")

    def _on_bridge_link(self, url: str) -> None:
        """Link clicado e capturado pelo JS (evita o Chromium trocar a página)."""
        if url.startswith(("http://", "https://", "mailto:")):
            self.externalRequested.emit(url)
        elif url.startswith("file:"):
            path = QUrl(url).toLocalFile()
            if path:
                self.fileRequested.emit(path)

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            log.warning("Falha ao carregar o documento no preview.")
            return

        if self._pending_line is not None:
            line = self._pending_line
            self._pending_line = None
            # Espera o layout assentar: no loadFinished as alturas dos blocos
            # ainda não refletem as fontes e as imagens.
            self.page().runJavaScript(
                "requestAnimationFrame(function(){"
                f"  window.scrollToLine && window.scrollToLine({line}, false);"
                "});"
            )
        self.documentLoaded.emit()

    def closeEvent(self, event) -> None:  # noqa: N802 - assinatura do Qt
        self._cleanup_temp_file()
        super().closeEvent(event)
