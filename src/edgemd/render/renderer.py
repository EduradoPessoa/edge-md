"""Markdown -> documento HTML completo, pronto para o QWebEngineView.

O renderer tem duas responsabilidades:

1. converter texto Markdown em corpo HTML usando o parser de ``plugins.py``;
2. embrulhar esse corpo num documento HTML autocontido — CSS embutido, JS do
   preview embutido, temas claro e escuro presentes ao mesmo tempo para que a
   troca de tema seja instantânea (sem re-render).

Sobre URLs: o documento é entregue ao Chromium via ``setHtml``, cujo
``baseUrl`` apontamos para a pasta de assets (é de lá que saem ``vendor/*.js``).
Por isso todo caminho relativo escrito no .md — imagens, links — é reescrito
para URL absoluta ``file://`` antes de entrar no documento. Sem isso, uma
imagem ao lado do .md não carregaria.
"""

from __future__ import annotations

import codecs
import html
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from edgemd.paths import asset_path
from edgemd.render.plugins import build_parser

log = logging.getLogger(__name__)

DEFAULT_THEME = "dark"
THEMES = ("light", "dark")

#: Esquemas de URL que nunca devem ser tratados como caminho relativo.
_ABSOLUTE_URL = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//|#)")

#: Atributos que carregam URL e precisam ser resolvidos contra a pasta do .md.
_URL_ATTR = re.compile(r'(?P<attr>\b(?:src|href))\s*=\s*"(?P<url>[^"]*)"', re.IGNORECASE)

#: Tamanho a partir do qual o preview automático é desencorajado.
LARGE_FILE_BYTES = 2 * 1024 * 1024


# --------------------------------------------------------------------------
# Leitura de arquivos
# --------------------------------------------------------------------------

def decode_bytes(data: bytes) -> tuple[str, str]:
    """Decodifica bytes de um .md tentando os encodings realistas no Windows.

    Ordem: BOM UTF-8/UTF-16 (declaração explícita, mais confiável), depois
    UTF-8 estrito, e por fim cp1252 — que é o que o Bloco de Notas e o Word
    produzem em português. cp1252 nunca falha porque mapeia quase todos os 256
    bytes, então ele fecha a cadeia sem ``errors=replace``.
    """
    if data.startswith(codecs.BOM_UTF8):
        return data.decode("utf-8-sig"), "utf-8-sig"
    if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        return data.decode("utf-16"), "utf-16"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    log.info("Arquivo não é UTF-8 válido; decodificando como cp1252.")
    return data.decode("cp1252", errors="replace"), "cp1252"


def detect_eol(data: bytes) -> str:
    """Descobre o fim de linha dominante para preservá-lo ao salvar."""
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def read_text_file(path: str | Path) -> tuple[str, str, str]:
    """Lê um arquivo de texto devolvendo ``(conteúdo, encoding, eol)``."""
    raw = Path(path).read_bytes()
    text, encoding = decode_bytes(raw)
    return text, encoding, detect_eol(raw)


# --------------------------------------------------------------------------
# Resolução de URLs relativas
# --------------------------------------------------------------------------

def _file_url(path: Path) -> str:
    """URL ``file://`` absoluta e percent-encoded a partir de um caminho."""
    return "file:///" + quote(str(path.resolve()).replace("\\", "/"), safe="/:")


def absolutize_urls(body: str, base_dir: Path | None) -> str:
    """Reescreve URLs relativas do corpo para ``file://`` absolutas.

    Ancoras (``#secao``), URLs com esquema e caminhos já absolutos passam
    intactos. Fragmentos em caminhos relativos (``outro.md#topo``) são
    preservados.
    """
    if base_dir is None:
        return body

    def replace(match: re.Match[str]) -> str:
        attr = match.group("attr")
        url = match.group("url")
        if not url or _ABSOLUTE_URL.match(url):
            return match.group(0)

        fragment = ""
        if "#" in url:
            url, _, fragment = url.partition("#")
            fragment = f"#{fragment}"
        if not url:
            return match.group(0)

        # Caminhos no Windows podem vir com barra ou barra invertida.
        relative = url.replace("/", "\\") if "\\" in url else url
        try:
            target = (base_dir / relative).resolve()
        except (OSError, ValueError):
            return match.group(0)
        return f'{attr}="{_file_url(target)}{fragment}"'

    return _URL_ATTR.sub(replace, body)


# --------------------------------------------------------------------------
# Assets de CSS/JS
# --------------------------------------------------------------------------

@lru_cache(maxsize=32)
def _read_asset(name: str) -> str:
    """Lê um asset de ``render/assets`` com cache (o preview re-renderiza muito)."""
    path = asset_path(*name.split("/"))
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        log.warning("Asset ausente: %s", path)
        return ""


def vendor_available() -> dict[str, bool]:
    """Quais bibliotecas vendorizadas existem em disco.

    O preview usa isto para não tentar carregar um ``<script>`` inexistente e
    para não anunciar suporte a Mermaid/KaTeX quando o passo de download
    (``python tools/fetch_vendor.py``) ainda não foi executado.
    """
    return {
        "mermaid": asset_path("vendor", "mermaid.min.js").exists(),
        "katex": asset_path("vendor", "katex", "katex.min.js").exists(),
        "katex_css": asset_path("vendor", "katex", "katex.min.css").exists(),
    }


# --------------------------------------------------------------------------
# Resultado
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RenderedDocument:
    """Documento pronto para exibição."""

    html: str
    body: str
    title: str
    base_dir: Path | None = None
    """Pasta do .md, usada como ``baseUrl`` no QWebEngineView.

    Passamos a pasta do documento (e não a de assets) porque o ``baseUrl`` é a
    rede de segurança do Chromium: se a reescrita de URLs deixar passar algum
    caminho relativo — um ``srcset``, um ``<video>`` com aspas simples, HTML
    cru — ele ainda resolve corretamente. Os assets do app usam URL ``file://``
    absoluta justamente para não dependerem daqui.
    """


# --------------------------------------------------------------------------
# Renderer
# --------------------------------------------------------------------------

class MarkdownRenderer:
    """Converte Markdown em documento HTML completo."""

    def __init__(self) -> None:
        self._md = build_parser()

    # -- corpo ------------------------------------------------------------
    def render_body(self, text: str, base_dir: Path | None = None) -> str:
        """Converte Markdown em HTML de corpo, com URLs já resolvidas."""
        body = self._md.render(text)
        return absolutize_urls(body, base_dir)

    # -- documento --------------------------------------------------------
    def render_document(
        self,
        text: str,
        *,
        doc_path: str | Path | None = None,
        title: str | None = None,
        show_mermaid: bool = True,
        show_math: bool = True,
        theme: str = DEFAULT_THEME,
        absolutize: bool = True,
        asset_urls: dict[str, str] | None = None,
    ) -> RenderedDocument:
        """Monta o documento HTML completo para o preview.

        ``theme`` define o ``data-theme`` inicial do ``<html>``. Passar o tema
        já na renderização evita o piscar de tema escuro quando o app está em
        modo claro: o JS do preview lê esse atributo ao carregar.

        ``absolutize=False`` preserva os caminhos relativos do Markdown. É o
        que a exportação usa: um HTML exportado com URLs ``file://`` absolutas
        só funcionaria naquela máquina, e não é isso que se espera de um
        arquivo exportado.

        ``asset_urls`` permite trocar as origens locais de Mermaid/KaTeX por
        CDN, para que o HTML exportado funcione em qualquer lugar.
        """
        base_dir = Path(doc_path).resolve().parent if doc_path else None
        body = self.render_body(text, base_dir if absolutize else None)
        resolved_title = title or self._derive_title(text, doc_path)
        assets = vendor_available()
        overrides = asset_urls or {}
        resolved_theme = theme if theme in THEMES else DEFAULT_THEME

        def vendor_url(key: str, default: str) -> str:
            if key in overrides:
                return overrides[key]
            return default

        html_doc = _DOCUMENT_TEMPLATE
        replacements = {
            "{{TITLE}}": html.escape(resolved_title),
            "{{CSS_BASE}}": _read_asset("base.css"),
            "{{CSS_THEME_LIGHT}}": _read_asset("theme-light.css"),
            "{{CSS_THEME_DARK}}": _read_asset("theme-dark.css"),
            "{{CSS_PYGMENTS_LIGHT}}": _read_asset("pygments-light.css"),
            "{{CSS_PYGMENTS_DARK}}": _read_asset("pygments-dark.css"),
            "{{CSS_KATEX}}": (
                f'@import url("{vendor_url("katex_css", _file_url(asset_path("vendor", "katex", "katex.min.css")))}");'
                if show_math and assets["katex_css"]
                else ""
            ),
            "{{BODY}}": body,
            "{{SCRIPT_PREVIEW}}": _read_asset("preview.js"),
            "{{MERMAID_ENABLED}}": "true" if show_mermaid and assets["mermaid"] else "false",
            "{{MATH_ENABLED}}": "true" if show_math and assets["katex"] else "false",
            "{{VENDOR_MERMAID}}": (
                vendor_url("mermaid", _file_url(asset_path("vendor", "mermaid.min.js")))
                if assets["mermaid"]
                else ""
            ),
            "{{VENDOR_KATEX}}": (
                vendor_url("katex", _file_url(asset_path("vendor", "katex", "katex.min.js")))
                if assets["katex"]
                else ""
            ),
            "{{THEME}}": resolved_theme,
        }
        for token, value in replacements.items():
            html_doc = html_doc.replace(token, value)
        return RenderedDocument(
            html=html_doc, body=body, title=resolved_title, base_dir=base_dir
        )

    # -- utilitários ------------------------------------------------------
    @staticmethod
    def _derive_title(text: str, doc_path: str | Path | None) -> str:
        """Título da janela: primeiro H1 do documento, senão o nome do arquivo."""
        match = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
        if match:
            return re.sub(r"[*_`]", "", match.group(1)).strip()
        if doc_path:
            return Path(doc_path).stem
        return "Sem título"


# --------------------------------------------------------------------------
# Template do documento
# --------------------------------------------------------------------------
# Usa marcadores {{TOKEN}} em vez de str.format porque o CSS e o JS embutidos
# estão cheios de chaves, que o format interpretaria como campos.

_DOCUMENT_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR" data-theme="{{THEME}}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title>
<style>{{CSS_BASE}}</style>
<style id="theme-light" data-theme-sheet="light">{{CSS_THEME_LIGHT}}
{{CSS_PYGMENTS_LIGHT}}</style>
<style id="theme-dark" data-theme-sheet="dark">{{CSS_THEME_DARK}}
{{CSS_PYGMENTS_DARK}}</style>
<style id="katex-import">{{CSS_KATEX}}</style>
</head>
<body>
<article class="markdown-body" id="content">{{BODY}}</article>
<div class="toast" id="toast" role="status" aria-live="polite"></div>
<script>window.__MD_CONFIG__ = {
  mermaid: {{MERMAID_ENABLED}},
  math: {{MATH_ENABLED}},
  mermaidSrc: "{{VENDOR_MERMAID}}",
  katexSrc: "{{VENDOR_KATEX}}"
};</script>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>{{SCRIPT_PREVIEW}}</script>
</body>
</html>
"""
