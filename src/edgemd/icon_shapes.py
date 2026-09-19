"""Desenho dos ícones das ações, em SVG.

Ficam como dados em Python, e não como arquivos ``.svg`` soltos, pelo mesmo
motivo que o ícone do app é desenhado em ``icons.py``: a cor precisa vir do
tema em tempo de execução. Um arquivo SVG teria cor fixa, e manter duas versões
(clara e escura) de cada ícone sairia de sincronia na primeira alteração.

Todos seguem a mesma grade para parecerem um conjunto:

* área de 24×24;
* traço sem preenchimento, pontas e cantos arredondados;
* espessura 1.7 (fina o bastante para não virar borrão em 16 px, grossa o
  bastante para sobreviver à redução);
* nenhum detalhe abaixo de ~2 px, que sumiria nos 16 px da barra.

O corpo de cada entrada é markup SVG puro, sem a tag ``<svg>`` — quem monta a
tag é :func:`svg_markup`, que injeta cor e espessura.
"""

from __future__ import annotations

#: Espessura padrão do traço, na grade de 24×24.
STROKE_WIDTH = 1.7

#: Círculos pequenos cheios (marcadores de lista) precisam de instruções
#: próprias: herdam o traço, mas devem ser preenchidos.
_DOT = 'fill="currentColor" stroke="none"'

ICONS: dict[str, str] = {
    # -- Arquivo -------------------------------------------------------
    "new": (
        '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
        '<path d="M14 3v5h5"/>'
        '<path d="M12 12.5v6M9 15.5h6"/>'
    ),
    "open": (
        '<path d="M3 8a2 2 0 0 1 2-2h3.6a1 1 0 0 1 .8.4L11 8.5h8a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
    ),
    "open-folder": (
        '<path d="M3 8a2 2 0 0 1 2-2h3.6a1 1 0 0 1 .8.4L11 8.5h8a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
        '<path d="M12 11.5v5M9.5 14h5"/>'
    ),
    "save": (
        '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>'
        '<path d="M16.5 21v-7.5h-9V21"/>'
        '<path d="M7 3v4.5h7"/>'
    ),
    "save-as": (
        '<path d="M19 13.5V10l-5-5H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h7"/>'
        '<path d="M7 3v4.5h7"/>'
        '<path d="M18.5 14.5l2.6 2.6-5.1 5.1H13.4v-2.6z"/>'
    ),
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "quit": (
        '<path d="M14 20h4a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-4"/>'
        '<path d="M10 16l-4-4 4-4"/>'
        '<path d="M6 12h10"/>'
    ),

    # -- Modos de exibição ---------------------------------------------
    "read": (
        '<path d="M2.5 12S6 6 12 6s9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z"/>'
        '<circle cx="12" cy="12" r="2.6"/>'
    ),
    "edit": (
        '<path d="M4 20h4L18.5 9.5a2.83 2.83 0 0 0-4-4L4 16z"/>'
        '<path d="M13.5 6.5l4 4"/>'
    ),
    "split": (
        '<rect x="3" y="4" width="18" height="16" rx="2.5"/>'
        '<path d="M12 4v16"/>'
    ),
    "editor-only": (
        '<rect x="3" y="4" width="18" height="16" rx="2.5"/>'
        '<path d="M9.5 9.5L7 12l2.5 2.5"/>'
        '<path d="M14.5 9.5L17 12l-2.5 2.5"/>'
    ),
    "sidebar": (
        '<rect x="3" y="4" width="18" height="16" rx="2.5"/>'
        '<path d="M9 4v16"/>'
        '<path d="M5 8h2M5 12h2"/>'
    ),
    "theme": (
        '<circle cx="12" cy="12" r="4.2"/>'
        '<path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2"/>'
        '<path d="M5.2 5.2l1.4 1.4M17.4 17.4l1.4 1.4M18.8 5.2l-1.4 1.4M6.6 17.4l-1.4 1.4"/>'
    ),
    "zoom-in": (
        '<circle cx="10.5" cy="10.5" r="6.5"/>'
        '<path d="M20.5 20.5l-5-5"/>'
        '<path d="M7.5 10.5h6M10.5 7.5v6"/>'
    ),
    "zoom-out": (
        '<circle cx="10.5" cy="10.5" r="6.5"/>'
        '<path d="M20.5 20.5l-5-5"/>'
        '<path d="M7.5 10.5h6"/>'
    ),

    # -- Formatação ----------------------------------------------------
    "bold": (
        '<path d="M7 4.5h5.5a3.75 3.75 0 0 1 0 7.5H7z"/>'
        '<path d="M7 12h6.5a3.75 3.75 0 0 1 0 7.5H7z"/>'
    ),
    "italic": (
        '<path d="M15.5 4.5h-5M13.5 19.5h-5"/>'
        '<path d="M14 4.5l-3 15"/>'
    ),
    "strikethrough": (
        # O "S" é uma curva contínua, e a barra passa por cima. Desenhar o S em
        # dois pedaços deixava a junção visível e o resultado parecia um cifrão.
        '<path d="M16.6 7.1c0-1.5-2-2.5-4.5-2.5S7.7 5.7 7.7 7.4c0 1.7 1.8 2.5 4.3 3.1'
        ' 2.5.6 4.5 1.4 4.5 3.2s-2.1 3-4.6 3-4.6-1.1-4.6-2.7"/>'
        '<path d="M3.8 12.1h16.4"/>'
    ),
    "code-inline": (
        '<path d="M8.5 8.5L5 12l3.5 3.5"/>'
        '<path d="M15.5 8.5L19 12l-3.5 3.5"/>'
        '<path d="M13.5 6l-3 12"/>'
    ),
    "link": (
        '<path d="M10.2 13.3a4 4 0 0 0 5.9 0l2.6-2.6a4.17 4.17 0 0 0-5.9-5.9l-1.3 1.3"/>'
        '<path d="M13.8 10.7a4 4 0 0 0-5.9 0l-2.6 2.6a4.17 4.17 0 0 0 5.9 5.9l1.3-1.3"/>'
    ),
    "h1": (
        '<path d="M4.5 5.5v13M12 5.5v13M4.5 12h7.5"/>'
        '<path d="M16.8 9.6l2.2-1.1v10"/>'
    ),
    "h2": (
        '<path d="M4.5 5.5v13M11 5.5v13M4.5 12H11"/>'
        '<path d="M15.5 10.4a2.1 2.1 0 1 1 3.6 1.5c-.7.9-3.6 3-3.6 3h4.2"/>'
    ),
    "h3": (
        '<path d="M4.5 5.5v13M11 5.5v13M4.5 12H11"/>'
        '<path d="M15.4 9.6h4.2l-2.6 3.4a2.3 2.3 0 1 1-1.7 4"/>'
    ),
    "list-bullet": (
        '<path d="M9 6.5h11M9 12h11M9 17.5h11"/>'
        f'<circle cx="4.6" cy="6.5" r="1.4" {_DOT}/>'
        f'<circle cx="4.6" cy="12" r="1.4" {_DOT}/>'
        f'<circle cx="4.6" cy="17.5" r="1.4" {_DOT}/>'
    ),
    "list-number": (
        # Os numerais são maiores do que pareceria natural e as linhas cedem
        # espaço para eles: em 16 px, dígito pequeno demais vira borrão e o
        # ícone fica igual ao de lista com marcadores.
        '<path d="M10.5 6.5h10M10.5 12h10M10.5 17.5h10"/>'
        '<path d="M3.2 7V3.9l1.7-.9"/>'
        '<path d="M2.9 9.8a1.6 1.6 0 1 1 2.7 1.2L2.9 13.4h2.9"/>'
        '<path d="M2.9 15.6h2.4l-1.5 1.9a1.6 1.6 0 1 1-1 2.7"/>'
    ),
    "task": (
        '<rect x="3" y="3" width="18" height="18" rx="4"/>'
        '<path d="M7.8 12.4l2.9 2.9 5.5-6"/>'
    ),
    "quote": (
        '<path d="M4 5v14"/>'
        '<path d="M9 8h11M9 12h11M9 16h7"/>'
    ),
    "code-block": (
        '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/>'
        '<path d="M9.8 9.8L7.6 12l2.2 2.2"/>'
        '<path d="M14.2 9.8L16.4 12l-2.2 2.2"/>'
    ),
    "table": (
        '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/>'
        '<path d="M3 10h18M3 14.5h18"/>'
        '<path d="M9.5 4.5v15M15 4.5v15"/>'
    ),
    "hr": (
        '<path d="M3.5 12h17"/>'
        '<path d="M7 6.5h10M7 17.5h10"/>'
    ),

    # -- Exportação ----------------------------------------------------
    "export-html": (
        '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h6"/>'
        '<path d="M14 3v5h5"/>'
        '<path d="M13 3.2V9h4.8"/>'
        '<path d="M18.5 21l3-3-3-3M14.5 18h7"/>'
    ),
    "export-pdf": (
        '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
        '<path d="M14 3v5h5"/>'
        '<path d="M12 11.5v7M9 15.5l3 3 3-3"/>'
    ),

    # -- Edição --------------------------------------------------------
    "undo": (
        '<path d="M4 9h11a5 5 0 0 1 0 10H8"/>'
        '<path d="M7.5 5.5L4 9l3.5 3.5"/>'
    ),
    "redo": (
        '<path d="M20 9H9a5 5 0 0 0 0 10h7"/>'
        '<path d="M16.5 5.5L20 9l-3.5 3.5"/>'
    ),
    "cut": (
        '<circle cx="6.5" cy="18" r="2.5"/>'
        '<circle cx="17.5" cy="18" r="2.5"/>'
        '<path d="M8.3 16.2L18 4M15.7 16.2L6 4"/>'
    ),
    "copy": (
        '<rect x="9" y="9" width="12" height="12" rx="2.5"/>'
        '<path d="M5.5 15H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v.5"/>'
    ),
    "paste": (
        '<path d="M9 4H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2"/>'
        '<rect x="9" y="2.5" width="6" height="3.5" rx="1.4"/>'
    ),
    "select-all": (
        '<rect x="3" y="3" width="18" height="18" rx="3"/>'
        '<path d="M7.5 12l3 3 6-6.5"/>'
    ),

    # -- Busca ---------------------------------------------------------
    "find": (
        '<circle cx="10.5" cy="10.5" r="6.5"/>'
        '<path d="M20.5 20.5l-5-5"/>'
    ),
    "find-next": (
        '<circle cx="10.5" cy="10.5" r="6.5"/>'
        '<path d="M20.5 20.5l-5-5"/>'
        '<path d="M8 17.5v-5M5.8 14.7L8 12.5l2.2 2.2"/>'
    ),
    "find-previous": (
        '<circle cx="10.5" cy="10.5" r="6.5"/>'
        '<path d="M20.5 20.5l-5-5"/>'
        '<path d="M8 3.5v5M5.8 6.3L8 8.5l2.2-2.2"/>'
    ),
    "replace": (
        '<path d="M3 8h9a3.5 3.5 0 0 1 0 7H6.5"/>'
        '<path d="M9 12L6 15l3 3"/>'
        '<path d="M21 12h-7M21 12l-2.5-2.5M21 12l-2.5 2.5"/>'
    ),

    # -- Exibição do editor --------------------------------------------
    "line-numbers": (
        '<path d="M4 6.5h2.2M4 12h2.2M4 17.5h2.2"/>'
        '<path d="M10 6.5h11M10 12h11M10 17.5h11"/>'
    ),
    "word-wrap": (
        '<path d="M4 6h16M4 18h9"/>'
        '<path d="M4 12h12.5a3 3 0 0 1 0 6h-2.5"/>'
        '<path d="M16 15.5L14 18l2 2.5"/>'
    ),
    "scroll-sync": (
        '<path d="M8 4.5v15M16 4.5v15"/>'
        '<path d="M4.5 9L8 5.5 11.5 9M12.5 15l3.5 3.5L19.5 15"/>'
    ),

    # -- Ferramentas / ajuda -------------------------------------------
    "association": (
        '<path d="M9.5 12h5"/>'
        '<path d="M10 8.2H7.8a3.8 3.8 0 0 0 0 7.6H10"/>'
        '<path d="M14 8.2h2.2a3.8 3.8 0 0 1 0 7.6H14"/>'
    ),
    "unlink": (
        '<path d="M10 8.2H7.8a3.8 3.8 0 0 0 0 7.6H10"/>'
        '<path d="M14 8.2h2.2a3.8 3.8 0 0 1 3 6.1"/>'
        '<path d="M4 4l16 16"/>'
    ),
    "reveal": (
        '<path d="M3 8a2 2 0 0 1 2-2h3.6l1.6 2H19a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
        '<path d="M12 10.5v6M9 13.5l3 3 3-3"/>'
    ),
    "info": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M12 11v5.5"/>'
        f'<circle cx="12" cy="7.8" r="1" {_DOT}/>'
    ),
    "refresh": (
        '<path d="M20 12a8 8 0 1 1-2.4-5.7"/>'
        '<path d="M20 4.5V10h-5.5"/>'
    ),
}


def svg_markup(body: str, color: str, size: int = 24, width: float = STROKE_WIDTH) -> str:
    """Monta o SVG completo de um ícone, com cor e espessura injetadas.

    ``currentColor`` no lugar da cor deixaria o trabalho para o Qt, que não
    resolve essa palavra-chave em SVG. Injetar a cor no texto é o que permite
    ter o mesmo desenho nos dois temas.
    """
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'width="{size}" height="{size}" fill="none" color="{color}" '
        f'stroke="{color}" stroke-width="{width}" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


def available() -> tuple[str, ...]:
    """Nomes dos ícones disponíveis, em ordem alfabética."""
    return tuple(sorted(ICONS))


#: Ícones efetivamente usados pelas ações da janela.
#:
#: Declarado aqui, junto do conjunto desenhado, para que o teste que compara os
#: dois não precise importar ``edgemd.window`` — que instancia o Chromium só
#: para existir. Um nome pedido e não desenhado daria um botão em branco na
#: barra de ferramentas.
USED_ACTIONS: tuple[str, ...] = (
    "new", "open", "open-folder", "save", "save-as",
    "export-html", "export-pdf", "close", "quit",
    "undo", "redo", "cut", "copy", "paste", "select-all",
    "find", "find-next", "find-previous", "replace",
    "bold", "italic", "strikethrough", "code-inline", "link",
    "code-block", "table", "h1", "h2", "h3", "quote",
    "list-bullet", "list-number", "task", "hr",
    "read", "split", "editor-only",
    "theme", "sidebar", "line-numbers", "word-wrap", "scroll-sync",
    "zoom-in", "zoom-out",
    "association", "unlink", "reveal", "refresh", "info",
)
