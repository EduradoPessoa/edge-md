"""Gera uma folha de contato com todos os ícones de ação.

Serve para conferência visual: um SVG pode renderizar sem erro e ainda assim
sair torto ou ilegível, e isso só se percebe olhando. Como os ícones são
tingidos pelo tema, a folha mostra as duas versões.

Uso:
    python tools/preview_icons.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PyQt6.QtCore import QRect, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from edgemd import icons, icon_shapes  # noqa: E402
from edgemd.theme import colors  # noqa: E402

#: Tamanhos exibidos lado a lado, para julgar legibilidade em cada contexto.
SIZES = (48, 32, 24, 16)

CELL_W = 150
CELL_H = 76


def render_theme(theme: str) -> QImage:
    palette = colors(theme)
    names = icon_shapes.available()

    columns = 5
    rows = (len(names) + columns - 1) // columns
    width = columns * CELL_W
    height = rows * CELL_H + 40

    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(palette.bg))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    painter.setPen(QColor(palette.fg_muted))
    painter.setFont(QFont("Segoe UI", 9))
    painter.drawText(
        QRect(12, 8, width - 24, 24),
        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        f"Tema {palette.label} — {len(names)} ícones · tamanhos {', '.join(str(s) for s in SIZES)} px",
    )

    for index, name in enumerate(names):
        column = index % columns
        row = index // columns
        x = column * CELL_W + 12
        y = row * CELL_H + 40

        icon = icons.action_icon(name, palette.icon_color())
        cursor = x
        for size in SIZES:
            pixmap: QPixmap = icon.pixmap(size, size)
            painter.drawPixmap(cursor, y, pixmap)
            cursor += size + 8

        painter.setPen(QColor(palette.fg_subtle))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(
            QRect(x, y + 46, CELL_W - 16, 18),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            name,
        )

    painter.end()
    return image


def main() -> int:
    app = QApplication(sys.argv)
    output = ROOT / "scratch"
    output.mkdir(parents=True, exist_ok=True)

    for theme in ("dark", "light"):
        image = render_theme(theme)
        target = output / f"icones-{theme}.png"
        image.save(str(target), "PNG")
        print(f"gerado: {target}  ({image.width()}x{image.height()})")

    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
