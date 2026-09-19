"""Gera os CSS de realce do Pygments usados pelo preview e pela exportação.

Escrito à mão seria inviável: o Pygments define corretamente mais de 80 tipos
de token. Aqui varremos os estilos do tema escolhido e emitimos apenas as
classes que o ``HtmlFormatter(nowrap=True)`` realmente produz.

Diferente do ``HtmlFormatter.get_style_defs()``, este gerador NÃO emite
``background``/``color`` no elemento raiz: o fundo do bloco de código é
controlado pelas variáveis CSS do tema (``--code-bg``), para que o código
acompanhe a superfície do app em vez de impor a cor do Pygments.

Uso:
    python tools/generate_pygments_css.py
"""

from __future__ import annotations

from pathlib import Path

from pygments.styles import get_style_by_name
from pygments.token import STANDARD_TYPES, Token

#: (arquivo de saída, estilo do Pygments, cabeçalho)
TARGETS = [
    (
        "pygments-dark.css",
        "github-dark",
        "Tema escuro — estilo github-dark",
    ),
    (
        "pygments-light.css",
        "friendly",
        "Tema claro — estilo friendly",
    ),
]

ASSETS = Path(__file__).resolve().parent.parent / "src" / "edgemd" / "render" / "assets"

HEADER = """/* ==========================================================================
   Realce de sintaxe — {desc}
   ARQUIVO GERADO. Não edite à mão: rode `python tools/generate_pygments_css.py`.
   As classes (.k, .s, .nf, ...) são os spans que o Pygments emite quando
   chamado com nowrap=True; cada uma é escopada sob .code-block__pre para não
   vazar para o resto do documento.
   ========================================================================== */

"""


def css_color(value: str) -> str:
    """Normaliza uma cor do Pygments para ``#rrggbb``.

    Dependendo da origem a string vem com ou sem ``#`` — ``list_styles()``
    devolve sem, ``style.highlight_color`` devolve com. Sem normalizar, o
    resultado é ``##6e7681``, que o Chromium descarta em silêncio.
    """
    value = (value or "").strip().lstrip("#")
    return f"#{value}" if value else ""


def declarations(attrs: dict) -> list[str]:
    """Converte os atributos de um token do Pygments em declarações CSS."""
    out: list[str] = []
    if attrs.get("color"):
        out.append(f"color: {css_color(attrs['color'])}")
    if attrs.get("bgcolor"):
        out.append(f"background-color: {css_color(attrs['bgcolor'])}")
    if attrs.get("bold"):
        out.append("font-weight: 600")
    if attrs.get("italic"):
        out.append("font-style: italic")
    if attrs.get("underline"):
        out.append("text-decoration: underline")
    return out


def root_color(style) -> str:
    """Cor de texto padrão do estilo, ou string vazia.

    Atenção: nem ``background_color`` nem ``highlight_color`` servem aqui —
    ``highlight_color`` é a cor de realce de *linha* (no estilo friendly é
    ``#ffffcc``, um amarelo pálido que ficaria invisível como cor de texto).
    A cor de texto padrão mora no token raiz ``Token``.

    Usamos ``list_styles()`` em vez de ``style.styles`` porque o dicionário
    cru guarda tanto strings quanto dicionários (``Token`` no github-dark é a
    string ``'#e6edf3'``), enquanto ``list_styles()`` sempre devolve um dict.
    """
    for token, attrs in style.list_styles():
        if token is Token:
            return css_color(attrs.get("color", ""))
    return ""


def build_css(style_name: str, description: str) -> str:
    style = get_style_by_name(style_name)
    scope = ".code-block__pre"

    # Sem cor raiz no estilo, fica valendo o --code-fg definido pelo tema no
    # base.css — que é exatamente o comportamento desejado.
    lines: list[str] = []
    base = root_color(style)
    if base:
        lines.append(f"{scope} {{ color: {base}; }}")

    for token, attrs in style.list_styles():
        cls = STANDARD_TYPES.get(token)
        if not cls:
            # Tokens intermediários (ex.: Token.Name) não viram classe própria;
            # o Pygments os agrupa no pai, então ignorar aqui é correto.
            continue
        decls = declarations(attrs)
        if not decls:
            continue
        lines.append(f"{scope} .{cls} {{ {'; '.join(decls)}; }}")

    return HEADER.format(desc=description) + "\n".join(lines) + "\n"


def main() -> int:
    for filename, style_name, description in TARGETS:
        css = build_css(style_name, description)
        path = ASSETS / filename
        path.write_text(css, encoding="utf-8")
        rules = css.count("{") - 1
        print(f"gerado: {path.name} ({rules} regras de token, estilo '{style_name}')")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
