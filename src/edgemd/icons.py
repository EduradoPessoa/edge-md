"""Ícones do aplicativo.

O ícone do produto é a arte fornecida (``EdgeMD.png`` na raiz), preparada por
``tools/make_icons.py`` em três arquivos dentro de ``resources/icons``:

* ``edgemd.ico`` — multi-resolução, usado na janela, na barra de tarefas e no
  registro de associação de arquivos;
* ``edgemd.png`` — 512 px, com a assinatura, para telas grandes;
* ``edgemd-small.png`` — 512 px, **sem** a assinatura, para a bandeja.

A variante sem assinatura existe porque em 16 a 32 px o texto "EdgeMD" vira uma
mancha cinza; sem ele, o "#" e a fita ficam maiores e continuam reconhecíveis.

Já os ícones das ações (negrito, salvar, …) são desenhados a partir de
``icon_shapes``, porque precisam acompanhar a cor do tema em tempo de execução.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPixmap,
)

from edgemd import icon_shapes
from edgemd.paths import icon_path

log = logging.getLogger(__name__)

#: Cor do ícone de reserva, caso os arquivos de arte não estejam no bundle.
FALLBACK_COLOR = "#2563eb"

#: Tamanhos gerados a partir do PNG quando só ele está disponível.
FALLBACK_SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw_icon(size: int = 256) -> QImage:
    """Ícone de reserva, desenhado em tempo de execução.

    Só é usado se a arte não estiver presente — o caso de um bundle mal
    montado. É deliberadamente simples: um quadrado de cantos arredondados com
    um "#", que remete ao Markdown. Não tenta imitar a arte oficial, para não
    passar por ela.
    """
    size = max(8, int(size))
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    radius = size * 0.22
    path = QPainterPath()
    path.addRoundedRect(QRectF(0.5, 0.5, size - 1.0, size - 1.0), radius, radius)
    painter.fillPath(path, QColor(FALLBACK_COLOR))

    font = QFont("Segoe UI", int(size * 0.58), QFont.Weight.Bold)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(
        QRectF(0, 0, size, size), int(Qt.AlignmentFlag.AlignCenter), "#"
    )
    painter.end()
    return image


def _icon_from_files(*names: str) -> QIcon:
    """Monta um ``QIcon`` a partir de arquivos, ignorando os que faltarem."""
    icon = QIcon()
    for name in names:
        path = icon_path(name)
        if path.is_file():
            icon.addFile(str(path))
    return icon


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    """Ícone do aplicativo, para janelas, diálogos e barra de tarefas."""
    icon = _icon_from_files("edgemd.ico", "edgemd.png")
    if not icon.isNull():
        return icon

    log.warning(
        "Arte do ícone não encontrada em resources/icons; usando o desenho de "
        "reserva. Rode: python tools/make_icons.py"
    )
    fallback = QIcon()
    for size in FALLBACK_SIZES:
        fallback.addPixmap(QPixmap.fromImage(draw_icon(size)))
    return fallback


@lru_cache(maxsize=1)
def tray_icon() -> QIcon:
    """Ícone da bandeja, sem a assinatura.

    O Windows usa 16 px na bandeja. Nesse tamanho o texto do ícone completo não
    é legível, então a bandeja usa a variante simplificada — que também é o que
    o ``.ico`` já traz nas resoluções pequenas, mas aqui de forma explícita,
    para o caso de o sistema pedir um tamanho que o ``.ico`` não tenha.
    """
    icon = _icon_from_files("edgemd-small.png")
    if not icon.isNull():
        # Os tamanhos grandes também vêm da arte completa, para o menu de
        # contexto e o balão de notificação não ficarem com a versão simplificada.
        completa = icon_path("edgemd.ico")
        if completa.is_file():
            icon.addFile(str(completa))
        return icon
    return app_icon()


def tray_icon() -> QIcon:
    """Ícone da bandeja.

    O Windows usa 16 px na bandeja, então fornecer os tamanhos menores
    explicitamente evita que o sistema reduza o de 256 px e borre.
    """
    icon = app_icon()
    if not icon.isNull():
        return icon
    return QIcon(QPixmap.fromImage(draw_icon(32)))


def dot_badge_icon(base: QIcon | None = None, color: str = "#e0a33e") -> QIcon:
    """Ícone com um ponto no canto, indicando alterações não salvas.

    O ponto é desenhado por cima da arte, em cada tamanho, porque o aviso de
    "tem coisa não salva" precisa aparecer justamente quando a janela está
    escondida na bandeja — é o único sinal visível nesse estado.
    """
    icon = base or tray_icon()
    result = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        pixmap = icon.pixmap(QSize(size, size))
        if pixmap.isNull():
            pixmap = QPixmap.fromImage(draw_icon(size))
        # O pixmap pode vir com fator de escala; desenhar nas coordenadas do
        # device evita o ponto sair fora de lugar em tela HiDPI.
        ratio = pixmap.devicePixelRatio() or 1.0
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        dot = max(3.0, size * 0.36) * ratio
        margem = 0.5 * ratio
        painter.drawEllipse(
            QRectF(
                pixmap.width() - dot - margem,
                pixmap.height() - dot - margem,
                dot,
                dot,
            )
        )
        painter.end()
        result.addPixmap(pixmap)
    return result


# --------------------------------------------------------------------------
# Ícones das ações
# --------------------------------------------------------------------------

#: Tamanhos gerados por ícone. O Qt escolhe o adequado conforme o contexto
#: (barra de ferramentas, menu) e a escala de DPI da tela.
ACTION_SIZES = (16, 20, 24, 32, 48)


@lru_cache(maxsize=512)
def _render_action(name: str, color: str, size: int) -> QPixmap:
    """Renderiza um ícone de ação num tamanho, já colorido.

    Um ``QSvgRenderer`` por chamada é aceitável porque o resultado fica em
    cache: cada combinação (ícone, cor, tamanho) é rasterizada uma vez só.
    """
    from PyQt6.QtSvg import QSvgRenderer

    body = icon_shapes.ICONS.get(name)
    if body is None:
        log.warning("Ícone desconhecido: %s", name)
        return QPixmap()

    markup = icon_shapes.svg_markup(body, color, size)
    renderer = QSvgRenderer(markup.encode("utf-8"))
    if not renderer.isValid():
        log.warning("SVG inválido para o ícone '%s'", name)
        return QPixmap()

    # Renderiza com fator de escala para o ícone sair nítido em telas HiDPI.
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.end()

    pixmap.setDevicePixelRatio(ratio)
    return pixmap


@lru_cache(maxsize=128)
def action_icon(name: str, color: str) -> QIcon:
    """Ícone monocromático de uma ação, na cor pedida.

    A cor vem do tema e entra no desenho, então trocar de tema exige descartar
    o cache — o que :func:`clear_action_cache` faz.
    """
    icon = QIcon()
    for size in ACTION_SIZES:
        pixmap = _render_action(name, color, size)
        if not pixmap.isNull():
            icon.addPixmap(pixmap)
    return icon


def clear_action_cache() -> None:
    """Descarta os ícones em cache.

    Chamado quando o tema muda: as cores estão gravadas nos pixmaps, então o
    cache antigo mostraria ícones com a cor do tema anterior.
    """
    _render_action.cache_clear()
    action_icon.cache_clear()


def available_actions() -> tuple[str, ...]:
    """Nomes dos ícones de ação disponíveis."""
    return icon_shapes.available()
