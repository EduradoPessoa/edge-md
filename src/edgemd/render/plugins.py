"""Montagem do parser markdown-it-py e de suas extensões.

Cada extensão é importada de forma tolerante: se um plugin opcional não estiver
instalado, o app continua renderizando o Markdown básico em vez de morrer no
import. Isso importa porque o pacote roda tanto no código-fonte quanto num
bundle PyInstaller, onde um plugin pode ter ficado de fora da coleta.
"""

from __future__ import annotations

import html
import logging
from typing import Any, Callable

from markdown_it import MarkdownIt

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Realce de sintaxe
# --------------------------------------------------------------------------

def _pygments_formatter(nowrap: bool = True) -> Any | None:
    """HtmlFormatter do Pygments, ou None se o Pygments não estiver presente."""
    try:
        from pygments.formatters import HtmlFormatter
    except ImportError:  # pragma: no cover - dependência declarada
        log.warning("Pygments ausente: blocos de código sairão sem cor.")
        return None
    return HtmlFormatter(nowrap=nowrap)


def highlight_code(code: str, lang: str, _attrs: str) -> str:
    """Callback de realce para blocos de código com cerca (```).

    Devolve o HTML completo do bloco, já com o botão de copiar. O markdown-it
    usa o retorno como está quando ele começa com ``<``, então assumimos o
    controle total da marcação — é o que permite ter o botão e o rótulo de
    linguagem sem pós-processar o HTML.
    """
    language = (lang or "").strip()

    # Mermaid não é código: vira um contêiner que o JS do preview renderiza.
    if language.lower() in {"mermaid", "mmd"}:
        escaped = html.escape(code, quote=False)
        return (
            '<div class="diagram-block" data-diagram="mermaid">'
            f'<pre class="mermaid-source">{escaped}</pre>'
            "</div>"
        )

    formatter = _pygments_formatter()
    inner: str
    if formatter is not None and language:
        try:
            from pygments import highlight as pygments_highlight
            from pygments.lexers import get_lexer_by_name
            from pygments.util import ClassNotFound

            lexer = get_lexer_by_name(language, stripall=False)
            inner = pygments_highlight(code, lexer, formatter)
        except ClassNotFound:
            inner = html.escape(code, quote=False)
        except Exception:  # pragma: no cover - lexer problemático
            log.exception("Falha ao realçar bloco de código (%s)", language)
            inner = html.escape(code, quote=False)
    else:
        inner = html.escape(code, quote=False)

    label = language or "texto"
    code_attr = f' class="language-{html.escape(language)}"' if language else ""
    return (
        f'<div class="code-block" data-lang="{html.escape(language)}">'
        '<div class="code-block__bar">'
        f'<span class="code-block__lang">{html.escape(label)}</span>'
        '<button class="code-block__copy" type="button" data-copy>Copiar</button>'
        "</div>"
        f'<pre class="code-block__pre"><code{code_attr}>{inner}</code></pre>'
        "</div>"
    )


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

def _try_plugin(md: MarkdownIt, name: str, loader: Callable[[], Any], *args: Any, **kwargs: Any) -> bool:
    """Aplica um plugin opcional; devolve False (com log) se indisponível."""
    try:
        plugin = loader()
    except ImportError:
        log.info("Plugin '%s' indisponível; seguindo sem ele.", name)
        return False
    try:
        if kwargs:
            md.use(plugin, *args, **kwargs)
        elif args:
            md.use(plugin, *args)
        else:
            md.use(plugin)
    except Exception:
        log.exception("Falha ao aplicar o plugin '%s'.", name)
        return False
    return True


def build_parser() -> MarkdownIt:
    """Cria o parser Markdown com todas as extensões disponíveis."""
    # "commonmark" é o preset mais previsível. Ativamos tabelas e riscado à mão
    # para não depender do preset "gfm-like", que exige linkify-it-py instalado.
    md = MarkdownIt(
        "commonmark",
        {
            "html": True,          # HTML cru no .md é respeitado
            "linkify": False,
            "typographer": True,   # aspas curvas, travessões, reticências
            "breaks": False,       # CommonMark: quebra simples não vira <br>
            "highlight": highlight_code,
        },
    )

    # Regras já presentes no parser do markdown-it-py.
    for rule in ("table", "strikethrough"):
        try:
            md.enable(rule)
        except Exception:  # pragma: no cover - regra ausente na versão
            log.info("Regra '%s' indisponível nesta versão do markdown-it-py.", rule)

    if _try_plugin(md, "tasklists", lambda: __import__(
        "mdit_py_plugins.tasklists", fromlist=["tasklists_plugin"]
    ).tasklists_plugin, enabled=True):
        pass

    _try_plugin(
        md, "footnote",
        lambda: __import__("mdit_py_plugins.footnote", fromlist=["footnote_plugin"]).footnote_plugin,
    )
    _try_plugin(
        md, "deflist",
        lambda: __import__("mdit_py_plugins.deflist", fromlist=["deflist_plugin"]).deflist_plugin,
    )
    _try_plugin(
        md, "anchors",
        lambda: __import__("mdit_py_plugins.anchors", fromlist=["anchors_plugin"]).anchors_plugin,
        min_level=1, max_level=6, slug_func=_slugify, permalink=False,
    )

    # Matemática: o plugin protege $...$ e $$...$$ do processamento Markdown
    # (senão um "_" dentro da fórmula viraria itálico). O KaTeX no preview
    # depois converte os elementos resultantes.
    _try_plugin(
        md, "dollarmath",
        lambda: __import__("mdit_py_plugins.dollarmath", fromlist=["dollarmath_plugin"]).dollarmath_plugin,
        allow_labels=True, allow_space=True, double_inline=True,
    )

    # Sincronia de scroll: cada bloco ganha data-line com sua linha de origem.
    md.use(source_lines_plugin)

    return md


# --------------------------------------------------------------------------
# Rastreio de linhas de origem
# --------------------------------------------------------------------------

#: Tokens de bloco que valem a pena marcar (os que a sincronia de scroll usa).
_TRACKED_BLOCKS = frozenset({
    "paragraph_open",
    "heading_open",
    "blockquote_open",
    "bullet_list_open",
    "ordered_list_open",
    "list_item_open",
    "table_open",
    "fence",
    "hr",
    "dl_open",
    "dt_open",
    "dd_open",
    "footnote_block_open",
})


def source_lines_plugin(md: MarkdownIt) -> None:
    """Marca tokens de bloco com ``data-line`` (1-based) da linha no .md.

    Sem isso, a sincronia de scroll editor<->preview só poderia ser
    proporcional, que erra feio em documentos com blocos de altura muito
    diferente. Com ``data-line``, o preview sabe exatamente qual elemento
    corresponde à linha visível no editor.

    O alternador ``data-marker`` evita marcar duas vezes os tokens aninhados:
    ``bullet_list_open`` e ``list_item_open`` apontam para a mesma linha, e o
    JS só precisa do ancestral mais próximo.
    """

    def add_source_lines(state: Any) -> bool:
        def walk(tokens: list[Any]) -> None:
            for token in tokens:
                if token.type in _TRACKED_BLOCKS and getattr(token, "map", None):
                    token.attrSet("data-line", str(token.map[0] + 1))
                children = getattr(token, "children", None)
                if children:
                    walk(children)

        walk(state.tokens)
        return False

    md.core.ruler.push("source_lines", add_source_lines)


def _slugify(text: str) -> str:
    """Gera id de âncora a partir do título, preservando acentos."""
    import re
    import unicodedata

    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", ascii_only).strip().lower()
    return re.sub(r"[\s_]+", "-", slug) or "secao"
