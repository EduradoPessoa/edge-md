"""Exportação do documento renderizado para HTML autônomo e para PDF.

**HTML.** O objetivo é um arquivo que funcione em qualquer máquina, não só
naquela onde foi gerado. Isso exige duas coisas:

* manter os caminhos relativos do Markdown como estão (nada de ``file://``
  absoluto, que apontaria para pastas locais inexistentes em outro PC);
* trocar as origens locais de Mermaid/KaTeX por CDN, já que os arquivos
  vendorizados não viajam junto com o HTML.

As imagens locais são embutidas como ``data:`` URI, então o HTML resultante é
realmente um arquivo só. Isso tem preço: um documento com muitas fotos gera um
HTML grande. Por isso o comportamento é configurável.

**PDF.** Usa o ``printToPdf`` do Chromium. A impressão precisa esperar o
Mermaid e o KaTeX terminarem, que são assíncronos, então há uma espera
deliberada depois do ``loadFinished`` — imprimir naquele instante capturaria os
diagramas ainda não desenhados.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
from pathlib import Path

from PyQt6.QtCore import QMarginsF, QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QPageLayout, QPageSize
from PyQt6.QtWebEngineCore import QWebEnginePage

from edgemd.paths import asset_path
from edgemd.render import MarkdownRenderer

log = logging.getLogger(__name__)

#: Versões usadas nas URLs de CDN quando não há manifesto.
FALLBACK_VERSIONS = {"mermaid": "11", "katex": "0.16.11"}

#: Tempo de espera após o loadFinished antes de imprimir o PDF, para dar tempo
#: ao Mermaid/KaTeX assíncronos de desenhar.
PRINT_SETTLE_MS = 1400

_IMG_SRC = re.compile(r'(<img\b[^>]*?\bsrc\s*=\s*")([^"]+)(")', re.IGNORECASE)
_SKIP_SCHEME = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//)")


def vendor_versions() -> dict[str, str]:
    """Versões vendorizadas, lidas do manifesto gerado por fetch_vendor.py."""
    manifest = asset_path("vendor", "MANIFEST.json")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        packages = data.get("packages", {})
        if isinstance(packages, dict) and packages:
            return {k: str(v) for k, v in packages.items()}
    except (OSError, json.JSONDecodeError, AttributeError):
        log.debug("Manifesto de vendor ausente ou inválido; usando versões padrão.")
    return dict(FALLBACK_VERSIONS)


def cdn_urls() -> dict[str, str]:
    """URLs de CDN para Mermaid e KaTeX, na mesma versão vendorizada."""
    versions = vendor_versions()
    mermaid = versions.get("mermaid", FALLBACK_VERSIONS["mermaid"])
    katex = versions.get("katex", FALLBACK_VERSIONS["katex"])
    return {
        "mermaid": f"https://cdn.jsdelivr.net/npm/mermaid@{mermaid}/dist/mermaid.min.js",
        "katex": f"https://cdn.jsdelivr.net/npm/katex@{katex}/dist/katex.min.js",
        "katex_css": f"https://cdn.jsdelivr.net/npm/katex@{katex}/dist/katex.min.css",
    }


# --------------------------------------------------------------------------
# Imagens embutidas
# --------------------------------------------------------------------------

def embed_images(body: str, base_dir: Path) -> tuple[str, int, int]:
    """Troca ``<img src>`` locais por ``data:`` URIs.

    Devolve ``(novo_corpo, embutidas, falhas)``. Imagens remotas ou já em
    ``data:`` passam intactas.
    """
    embedded = 0
    failed = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal embedded, failed
        prefix, url, suffix = match.groups()

        if _SKIP_SCHEME.match(url):
            return match.group(0)

        candidate = (base_dir / url.replace("/", "\\")).resolve()
        if not candidate.is_file():
            failed += 1
            return match.group(0)

        try:
            payload = candidate.read_bytes()
        except OSError:
            failed += 1
            return match.group(0)

        mime, _ = mimetypes.guess_type(candidate.name)
        if not mime:
            mime = "application/octet-stream"
        encoded = base64.b64encode(payload).decode("ascii")
        embedded += 1
        return f"{prefix}data:{mime};base64,{encoded}{suffix}"

    return _IMG_SRC.sub(replace, body), embedded, failed


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

class ExportResult:
    """Resumo de uma exportação, para exibir ao usuário."""

    def __init__(self, target: Path, size: int, embedded: int = 0, failed: int = 0) -> None:
        self.target = target
        self.size = size
        self.embedded = embedded
        self.failed = failed

    @property
    def size_label(self) -> str:
        if self.size >= 1024 * 1024:
            return f"{self.size / 1024 / 1024:.1f} MB"
        return f"{self.size / 1024:.0f} KB"


def export_html(
    renderer: MarkdownRenderer,
    text: str,
    doc_path: str | Path | None,
    target: str | Path,
    *,
    theme: str = "dark",
    embed_local_images: bool = True,
    show_mermaid: bool = True,
    show_math: bool = True,
) -> ExportResult:
    """Gera um HTML autônomo a partir do Markdown.

    Levanta ``OSError`` se não conseguir escrever — o chamador mostra o erro.
    """
    target_path = Path(target).resolve()

    document = renderer.render_document(
        text,
        doc_path=doc_path,
        title=None,
        show_mermaid=show_mermaid,
        show_math=show_math,
        theme=theme,
        # Preserva caminhos relativos: o HTML pode ser aberto em outra máquina.
        absolutize=False,
        asset_urls=cdn_urls(),
    )

    body = document.body
    embedded = failed = 0
    if embed_local_images and doc_path:
        body, embedded, failed = embed_images(body, Path(doc_path).resolve().parent)

    # A reescrita do corpo é feita por substituição única do corpo original,
    # que é a única parte do documento sob nosso controle.
    html = document.html.replace(document.body, body, 1)

    # O HTML exportado não roda dentro do Qt, então o canal de comunicação do
    # Chromium não existe. Removemos a tag para não deixar um 404 no console
    # de quem abrir o arquivo.
    html = html.replace('<script src="qrc:///qtwebchannel/qwebchannel.js"></script>', "")

    data = html.encode("utf-8")
    target_path.write_bytes(data)
    return ExportResult(target_path, len(data), embedded, failed)


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------

class PdfExporter(QObject):
    """Exporta para PDF usando uma página offscreen do Chromium.

    Usa uma ``QWebEnginePage`` própria em vez da preview visível: assim a
    exportação não pisca na tela nem depende do que está sendo exibido no
    momento. A instância precisa sobreviver até o sinal de conclusão, então o
    chamador deve guardar a referência.
    """

    #: (caminho, sucesso)
    finished = pyqtSignal(str, bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._page: QWebEnginePage | None = None
        self._target: Path | None = None
        self._timer: QTimer | None = None

    def export(
        self,
        renderer: MarkdownRenderer,
        text: str,
        doc_path: str | Path | None,
        target: str | Path,
        *,
        theme: str = "light",
        show_mermaid: bool = True,
        show_math: bool = True,
    ) -> None:
        """Inicia a exportação. O resultado chega pelo sinal :attr:`finished`."""
        self._target = Path(target).resolve()

        # O tema já entra na renderização (render_document), então o documento
        # sai pronto — sem pós-processar o HTML, que é frágil.
        document = renderer.render_document(
            text,
            doc_path=doc_path,
            show_mermaid=show_mermaid,
            show_math=show_math,
            theme=theme,
        )

        self._page = QWebEnginePage(self)
        self._page.loadFinished.connect(self._on_loaded)

        base = (
            QUrl.fromLocalFile(str(document.base_dir) + "/")
            if document.base_dir
            else QUrl("about:blank")
        )
        self._page.setHtml(document.html, base)

    def _on_loaded(self, ok: bool) -> None:
        if not ok or self._page is None or self._target is None:
            self._finish(False)
            return

        # Mermaid e KaTeX desenham de forma assíncrona depois do loadFinished.
        # Sem esta espera, o PDF sairia com os diagramas em branco.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._print)
        self._timer.start(PRINT_SETTLE_MS)

    def _print(self) -> None:
        if self._page is None or self._target is None:
            self._finish(False)
            return

        self._page.pdfPrintingFinished.connect(self._on_print_finished)
        layout = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(14, 14, 14, 14),
            QPageLayout.Unit.Millimeter,
        )
        self._page.printToPdf(str(self._target), layout)

    def _on_print_finished(self, path: str, success: bool) -> None:
        if not success:
            log.error("Falha ao gerar o PDF em %s", path)
        self._finish(success)

    def _finish(self, success: bool) -> None:
        target = str(self._target) if self._target else ""
        if self._page is not None:
            self._page.deleteLater()
            self._page = None
        self.finished.emit(target, success)
