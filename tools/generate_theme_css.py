"""Gera ``render/assets/theme-*.css`` a partir da paleta de ``edgemd.theme``.

Por que gerar em vez de manter os arquivos à mão: o preview é HTML no Chromium
e o resto da interface é Qt. Enquanto as cores viveram nos dois lugares, elas
divergiram — foi assim que trocar o tema passou a mudar só o documento e deixar
menus e barras no visual nativo.

Agora ``edgemd/theme.py`` é a única fonte, e este script materializa a parte
que o Chromium precisa ler. O QSS do Qt sai da mesma paleta, em memória.

Uso:
    python tools/generate_theme_css.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from edgemd.theme import THEMES, colors, web_css  # noqa: E402

ASSETS = ROOT / "src" / "edgemd" / "render" / "assets"

HEADER = """/* ==========================================================================
   Tema {label} — ARQUIVO GERADO.
   Não edite à mão: as cores vivem em ``src/edgemd/theme.py``, que alimenta
   tanto este CSS quanto o QSS da interface Qt. Rode
   ``python tools/generate_theme_css.py`` depois de mudar a paleta.
   ========================================================================== */

"""


def main() -> int:
    for theme in THEMES:
        target = ASSETS / f"theme-{theme}.css"
        css = HEADER.format(label=colors(theme).label) + web_css(theme)
        target.write_text(css, encoding="utf-8")
        variaveis = len(colors(theme).css_variables())
        print(f"gerado: {target.name}  ({variaveis} variáveis, tema '{theme}')")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
