"""Gera uma imagem de teste para o documento de demonstração.

Existe para que o demo.md exercite o carregamento de imagens relativas — o
caminho mais fácil de quebrar, porque depende do baseUrl do Chromium.

Uso:
    python tools/make_demo_image.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "docs-exemplo" / "imagens" / "formas.png"


def main() -> int:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Pillow não instalado; a imagem de demonstração não foi gerada.")
        return 0

    width, height = 640, 220
    image = Image.new("RGB", (width, height), "#1c1f26")
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (16, 16, width - 16, height - 16), radius=14,
        outline="#3a3f4b", width=2,
    )

    # Formas geométricas simples: servem para confirmar visualmente que a
    # imagem foi carregada, sem depender de nenhuma fonte.
    draw.ellipse((52, 56, 172, 176), fill="#6ea8fe")
    draw.rectangle((204, 72, 324, 176), fill="#52c98a")
    draw.polygon([(356, 176), (420, 56), (484, 176)], fill="#e0a33e")
    draw.rounded_rectangle((516, 88, 596, 176), radius=10, fill="#c9a0ff")

    draw.text((52, 28), "imagem relativa carregada", fill="#a2a9b8")

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    image.save(TARGET, "PNG")
    print(f"gerado: {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
