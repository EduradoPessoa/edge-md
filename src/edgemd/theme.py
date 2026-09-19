"""Tema do aplicativo: uma paleta, duas saídas (web e Qt).

O problema que este módulo resolve: o preview é HTML dentro do Chromium e o
resto da interface é Qt. São dois motores de estilo que não se conhecem, então
manter as cores em dois lugares garante que uma hora eles divergem — foi
exatamente o que aconteceu antes: trocar o tema mudava o documento e deixava
menus, barras e barra lateral no visual nativo.

Aqui as cores são declaradas uma vez e projetadas em três saídas:

* :func:`web_css` — o bloco de variáveis que o CSS do preview consome
  (``--bg``, ``--fg``, ...). ``tools/generate_theme_css.py`` grava isso em
  ``render/assets/theme-*.css``, então o preview nunca tem valores próprios.
* :func:`qt_stylesheet` — o QSS aplicado em ``QApplication``, que veste menus,
  barra de ferramentas, abas, barra lateral, barra de status e diálogos.
* :func:`qt_palette` — complementa o QSS no que ele não cobre (texto
  desabilitado, cores de seleção em widgets nativos, dicas).

O estilo ``Fusion`` é forçado junto: o estilo nativo do Windows ignora boa parte
do QSS, e sem ele o tema escuro sairia pela metade.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

THEMES = ("light", "dark")
DEFAULT_THEME = "dark"


@dataclass(frozen=True)
class ThemeColors:
    """Todas as cores e medidas de um tema.

    Os nomes espelham as variáveis CSS já usadas por ``base.css`` para que a
    projeção para web seja direta e sem dicionário intermediário.
    """

    label: str

    # Superfícies
    bg: str
    bg_elev: str
    bg_sunken: str
    border: str
    border_strong: str
    hover: str

    # Texto
    fg: str
    fg_muted: str
    fg_subtle: str
    fg_disabled: str

    # Destaque
    accent: str
    accent_soft: str
    selection: str
    selection_bg: str
    selection_fg: str

    # Botão primário (o "Editar" da faixa, ações de destaque)
    button_bg: str
    button_bg_hover: str
    button_bg_pressed: str
    button_fg: str

    # Estados
    ok: str
    warn: str
    danger: str

    # Busca no editor: todas as ocorrências e a ocorrência atual.
    # Âmbar, e não o azul da seleção, para não se confundir com texto
    # selecionado — os dois aparecem ao mesmo tempo durante uma substituição.
    match_bg: str
    match_current_bg: str
    match_current_fg: str

    # Código
    code_bg: str
    code_bar_bg: str
    code_fg: str
    code_inline_bg: str
    code_inline_border: str
    code_inline_fg: str

    # Citação e tabela
    quote_bar: str
    quote_bg: str
    table_head_bg: str
    table_stripe: str
    table_hover: str

    # Cromo
    scrollbar: str
    scrollbar_hover: str
    toast_bg: str
    toast_fg: str

    # Medidas e tipografia (iguais nos dois temas)
    radius_sm: str
    radius_md: str
    shadow_lg: str
    font_sans: str
    font_mono: str
    font_size: str
    line_height: str
    content_width: str

    # -- projeções ------------------------------------------------------
    def css_variables(self) -> dict[str, str]:
        """Variáveis CSS do preview, na ordem em que aparecem no arquivo."""
        return {
            "bg": self.bg,
            "bg-elev": self.bg_elev,
            "border": self.border,
            "border-strong": self.border_strong,
            "fg": self.fg,
            "fg-muted": self.fg_muted,
            "fg-subtle": self.fg_subtle,
            "accent": self.accent,
            "accent-soft": self.accent_soft,
            "selection": self.selection,
            "ok": self.ok,
            "warn": self.warn,
            "code-bg": self.code_bg,
            "code-bar-bg": self.code_bar_bg,
            "code-fg": self.code_fg,
            "code-inline-bg": self.code_inline_bg,
            "code-inline-border": self.code_inline_border,
            "code-inline-fg": self.code_inline_fg,
            "quote-bar": self.quote_bar,
            "quote-bg": self.quote_bg,
            "table-head-bg": self.table_head_bg,
            "table-stripe": self.table_stripe,
            "table-hover": self.table_hover,
            "scrollbar": self.scrollbar,
            "scrollbar-hover": self.scrollbar_hover,
            "toast-bg": self.toast_bg,
            "toast-fg": self.toast_fg,
            "font-sans": self.font_sans,
            "font-mono": self.font_mono,
            "font-size-base": self.font_size,
            "line-height": self.line_height,
            "content-width": self.content_width,
            "radius-sm": self.radius_sm,
            "radius-md": self.radius_md,
            "shadow-lg": self.shadow_lg,
        }

    def icon_color(self) -> str:
        """Cor dos ícones monocromáticos da barra de ferramentas."""
        return self.fg


# --------------------------------------------------------------------------
# Paletas
# --------------------------------------------------------------------------

#: Medidas compartilhadas pelos dois temas.
_SHARED: dict[str, str] = {
    "radius_sm": "5px",
    "radius_md": "9px",
    "shadow_lg": "0 8px 28px rgba(0, 0, 0, 0.45)",
    "font_sans": (
        '"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, '
        '"Inter", "Noto Sans", sans-serif'
    ),
    "font_mono": (
        '"Cascadia Code", "Cascadia Mono", "JetBrains Mono", "Consolas", '
        '"SF Mono", ui-monospace, monospace'
    ),
    "font_size": "16px",
    "line_height": "1.7",
    "content_width": "54rem",
}

DARK = ThemeColors(
    label="escuro",
    bg="#16181d",
    bg_elev="#1c1f26",
    bg_sunken="#111316",
    border="#2a2e38",
    border_strong="#3a3f4b",
    hover="#242833",
    fg="#e4e7ee",
    fg_muted="#a2a9b8",
    fg_subtle="#6f7787",
    fg_disabled="#4d5462",
    accent="#6ea8fe",
    accent_soft="#252f3f",
    selection="rgba(110, 168, 254, 0.28)",
    # Fundo de seleção de menu/árvore: no escuro, um azul contido com texto
    # claro lê melhor do que azul vivo com texto escuro.
    selection_bg="#2d4463",
    selection_fg="#ffffff",
    button_bg="#2563eb",
    button_bg_hover="#3b82f6",
    button_bg_pressed="#1d4ed8",
    button_fg="#ffffff",
    ok="#52c98a",
    warn="#e0a33e",
    danger="#f2555a",
    match_bg="#4d4426",
    match_current_bg="#e0a33e",
    match_current_fg="#1a1d23",
    code_bg="#101216",
    code_bar_bg="#1a1d23",
    code_fg="#d6dae3",
    code_inline_bg="#23272f",
    code_inline_border="#31363f",
    code_inline_fg="#f0a5a5",
    quote_bar="#3f5f8f",
    quote_bg="#1a1e26",
    table_head_bg="#1c1f26",
    table_stripe="rgba(255, 255, 255, 0.018)",
    table_hover="rgba(110, 168, 254, 0.07)",
    scrollbar="#363b45",
    scrollbar_hover="#474d59",
    toast_bg="#2b3140",
    toast_fg="#e9ecf3",
    **_SHARED,
)

LIGHT = ThemeColors(
    label="claro",
    bg="#fdfdfc",
    bg_elev="#f5f6f8",
    bg_sunken="#ffffff",
    border="#e3e6ea",
    border_strong="#cdd2d9",
    hover="#eceff3",
    fg="#1f2328",
    fg_muted="#59606d",
    fg_subtle="#828a96",
    fg_disabled="#b0b7c0",
    accent="#1f6feb",
    accent_soft="#e4edfd",
    selection="rgba(31, 111, 235, 0.2)",
    selection_bg="#1f6feb",
    selection_fg="#ffffff",
    button_bg="#1f6feb",
    button_bg_hover="#3b82f6",
    button_bg_pressed="#1a5fd0",
    button_fg="#ffffff",
    ok="#1a7f52",
    warn="#9a6700",
    danger="#c8342f",
    match_bg="#fdf0bf",
    match_current_bg="#f2b134",
    match_current_fg="#1f2328",
    code_bg="#f6f8fa",
    code_bar_bg="#eef1f4",
    code_fg="#1f2328",
    code_inline_bg="#f0f2f5",
    code_inline_border="#dfe3e8",
    code_inline_fg="#b5305a",
    quote_bar="#b6c2d1",
    quote_bg="#f7f8fa",
    table_head_bg="#f4f6f8",
    table_stripe="rgba(0, 0, 0, 0.014)",
    table_hover="rgba(31, 111, 235, 0.05)",
    scrollbar="#ccd2da",
    scrollbar_hover="#b3bcc7",
    toast_bg="#2b3140",
    toast_fg="#f4f6fa",
    **_SHARED,
)

PALETTES: dict[str, ThemeColors] = {"dark": DARK, "light": LIGHT}


def colors(theme: str) -> ThemeColors:
    """Paleta de um tema, com queda para o padrão se o nome for desconhecido."""
    return PALETTES.get(theme, PALETTES[DEFAULT_THEME])


# --------------------------------------------------------------------------
# Saída 1: variáveis CSS do preview
# --------------------------------------------------------------------------

def web_css(theme: str) -> str:
    """Bloco ``:root``/``[data-theme]`` consumido pelo preview."""
    palette = colors(theme)
    selector = ":root,\n[data-theme=\"dark\"]" if theme == "dark" else "[data-theme=\"light\"]"

    groups = [
        ("Superfícies", ["bg", "bg-elev", "border", "border-strong"]),
        ("Texto", ["fg", "fg-muted", "fg-subtle"]),
        ("Destaque", ["accent", "accent-soft", "selection", "ok", "warn"]),
        ("Código", [
            "code-bg", "code-bar-bg", "code-fg",
            "code-inline-bg", "code-inline-border", "code-inline-fg",
        ]),
        ("Citação", ["quote-bar", "quote-bg"]),
        ("Tabela", ["table-head-bg", "table-stripe", "table-hover"]),
        ("Barra de rolagem", ["scrollbar", "scrollbar-hover"]),
        ("Aviso flutuante", ["toast-bg", "toast-fg"]),
        ("Tipografia e medidas", [
            "font-sans", "font-mono", "font-size-base",
            "line-height", "content-width",
        ]),
        ("Formas", ["radius-sm", "radius-md", "shadow-lg"]),
    ]

    variables = palette.css_variables()
    lines = [f"{selector} {{", f"  color-scheme: {'dark' if theme == 'dark' else 'light'};"]
    for title, keys in groups:
        lines.append("")
        lines.append(f"  /* {title} */")
        for key in keys:
            lines.append(f"  --{key}: {variables[key]};")
    lines.append("}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Saída 2: QSS do aplicativo
# --------------------------------------------------------------------------

def qt_stylesheet(theme: str) -> str:
    """Folha de estilo de toda a interface Qt, derivada da mesma paleta."""
    c = colors(theme)

    return f"""
/* =========================================================================
   Gerado por edgemd.theme — não edite à mão.
   Veste os widgets do Qt com a mesma paleta do preview.
   ========================================================================= */

QWidget {{
    background-color: {c.bg};
    color: {c.fg};
}}

QMainWindow, QDialog {{
    background-color: {c.bg};
}}

/* -- Barra de menus ---------------------------------------------------- */
QMenuBar {{
    background-color: {c.bg_elev};
    color: {c.fg};
    border-bottom: 1px solid {c.border};
    padding: 1px 4px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 5px 10px;
    border-radius: {c.radius_sm};
}}
QMenuBar::item:selected {{
    background-color: {c.selection_bg};
    color: {c.selection_fg};
}}
QMenuBar::item:pressed {{
    background-color: {c.accent_soft};
}}

/* -- Menus ------------------------------------------------------------- */
QMenu {{
    background-color: {c.bg_elev};
    color: {c.fg};
    border: 1px solid {c.border_strong};
    border-radius: {c.radius_md};
    padding: 5px;
}}
QMenu::item {{
    padding: 6px 26px 6px 30px;
    border-radius: {c.radius_sm};
    min-width: 170px;
}}
QMenu::item:selected {{
    background-color: {c.selection_bg};
    color: {c.selection_fg};
}}
QMenu::item:disabled {{
    color: {c.fg_disabled};
}}
QMenu::separator {{
    height: 1px;
    background-color: {c.border};
    margin: 5px 10px;
}}
QMenu::icon {{
    padding-left: 8px;
}}
QMenu::indicator {{
    width: 16px;
    height: 16px;
    margin-left: 8px;
}}

/* -- Barra de ferramentas ---------------------------------------------- */
QToolBar {{
    background-color: {c.bg_elev};
    border: 0;
    border-bottom: 1px solid {c.border};
    padding: 4px 6px;
    spacing: 2px;
}}
QToolBar::separator {{
    background-color: {c.border};
    width: 1px;
    margin: 5px 6px;
}}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {c.radius_sm};
    padding: 5px;
    color: {c.fg};
}}
QToolButton:hover {{
    background-color: {c.hover};
    border-color: {c.border_strong};
}}
QToolButton:pressed {{
    background-color: {c.accent_soft};
}}
QToolButton:checked {{
    background-color: {c.accent_soft};
    border-color: {c.accent};
}}
QToolButton:disabled {{
    color: {c.fg_disabled};
}}

/* -- Abas -------------------------------------------------------------- */
QTabWidget::pane {{
    border: 0;
    border-top: 1px solid {c.border};
}}
QTabBar {{
    background-color: {c.bg};
    qproperty-drawBase: 0;
}}
QTabBar::tab {{
    background-color: {c.bg};
    color: {c.fg_muted};
    border: 0;
    border-right: 1px solid {c.border};
    padding: 7px 14px;
    margin: 0;
}}
QTabBar::tab:hover {{
    background-color: {c.hover};
    color: {c.fg};
}}
QTabBar::tab:selected {{
    background-color: {c.bg_elev};
    color: {c.fg};
    border-bottom: 2px solid {c.accent};
}}
QTabBar::close-button {{
    subcontrol-position: right;
}}

/* -- Barra lateral (árvore) -------------------------------------------- */
QTreeView {{
    background-color: {c.bg_sunken};
    color: {c.fg};
    border: 0;
    outline: 0;
    padding: 3px;
}}
QTreeView::item {{
    padding: 4px 4px;
    border-radius: {c.radius_sm};
    min-height: 20px;
}}
QTreeView::item:hover {{
    background-color: {c.hover};
}}
QTreeView::item:selected {{
    background-color: {c.selection_bg};
    color: {c.selection_fg};
}}
QTreeView::branch {{
    background: transparent;
}}
QHeaderView::section {{
    background-color: {c.table_head_bg};
    color: {c.fg_muted};
    border: 0;
    border-bottom: 1px solid {c.border};
    padding: 5px 8px;
}}

/* -- Campos de texto --------------------------------------------------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{
    background-color: {c.bg_sunken};
    color: {c.fg};
    border: 1px solid {c.border};
    border-radius: {c.radius_sm};
    padding: 5px 8px;
    selection-background-color: {c.selection_bg};
    selection-color: {c.selection_fg};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {c.accent};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
    color: {c.fg_disabled};
}}
QComboBox QAbstractItemView {{
    background-color: {c.bg_elev};
    color: {c.fg};
    border: 1px solid {c.border_strong};
    selection-background-color: {c.selection_bg};
    selection-color: {c.selection_fg};
}}

/* -- Botões ------------------------------------------------------------ */
QPushButton {{
    background-color: {c.bg_elev};
    color: {c.fg};
    border: 1px solid {c.border_strong};
    border-radius: {c.radius_sm};
    padding: 6px 14px;
}}
QPushButton:hover {{
    background-color: {c.hover};
    border-color: {c.accent};
}}
QPushButton:pressed {{
    background-color: {c.accent_soft};
}}
QPushButton:default {{
    background-color: {c.button_bg};
    color: {c.button_fg};
    border-color: {c.button_bg};
}}
QPushButton:default:hover {{
    background-color: {c.button_bg_hover};
}}
QPushButton:disabled {{
    color: {c.fg_disabled};
    border-color: {c.border};
}}

/* -- Faixa de modo (widgets nomeados) ---------------------------------- */
QWidget#modeBar {{
    background-color: {c.bg_elev};
    border-bottom: 1px solid {c.border};
}}
QLabel#modeBarLabel {{
    background: transparent;
    color: {c.fg_muted};
    font-size: 12px;
}}
QPushButton#modeBarButton {{
    background-color: {c.button_bg};
    color: {c.button_fg};
    border: 1px solid {c.button_bg};
    border-radius: 6px;
    padding: 4px 14px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#modeBarButton:hover {{
    background-color: {c.button_bg_hover};
    border-color: {c.button_bg_hover};
}}
QPushButton#modeBarButton:pressed {{
    background-color: {c.button_bg_pressed};
}}

/* -- Barra de busca do editor ------------------------------------------ */
QWidget#findBar {{
    background-color: {c.bg_elev};
    border-top: 1px solid {c.border};
}}
QWidget#findBar QLineEdit {{
    background-color: {c.bg_sunken};
    border: 1px solid {c.border};
    border-radius: {c.radius_sm};
    padding: 4px 8px;
}}
QWidget#findBar QLineEdit:focus {{
    border-color: {c.accent};
}}
/* Campo sem resultado: o contorno fica vermelho, que é o aviso mais direto
   de que a busca não encontrou nada. */
QWidget#findBar QLineEdit[noResults="true"] {{
    border-color: {c.danger};
}}
QLabel#findCount {{
    background: transparent;
    color: {c.fg_muted};
    font-size: 11px;
    min-width: 84px;
}}
QLabel#findError {{
    background: transparent;
    color: {c.danger};
    font-size: 11px;
}}
QToolButton#findToggle {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {c.radius_sm};
    padding: 3px 6px;
    color: {c.fg_muted};
    font-size: 11px;
    font-weight: 600;
}}
QToolButton#findToggle:hover {{
    background-color: {c.hover};
    border-color: {c.border_strong};
}}
QToolButton#findToggle:checked {{
    background-color: {c.accent_soft};
    border-color: {c.accent};
    color: {c.fg};
}}

/* -- Barra de status --------------------------------------------------- */
QStatusBar {{
    background-color: {c.bg_elev};
    color: {c.fg_muted};
    border-top: 1px solid {c.border};
}}
QStatusBar::item {{
    border: 0;
}}
QStatusBar QLabel {{
    background: transparent;
    color: {c.fg_muted};
}}

/* -- Divisores --------------------------------------------------------- */
QSplitter::handle {{
    background-color: {c.border};
}}
QSplitter::handle:horizontal {{
    width: 1px;
}}
QSplitter::handle:vertical {{
    height: 1px;
}}
QSplitter::handle:hover {{
    background-color: {c.accent};
}}

/* -- Barras de rolagem ------------------------------------------------- */
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 0;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background-color: {c.scrollbar};
    border-radius: 5px;
    min-height: 32px;
    min-width: 32px;
}}
QScrollBar::handle:hover {{
    background-color: {c.scrollbar_hover};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
    background: transparent;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* -- Dicas e diálogos -------------------------------------------------- */
QToolTip {{
    background-color: {c.toast_bg};
    color: {c.toast_fg};
    border: 1px solid {c.border_strong};
    border-radius: {c.radius_sm};
    padding: 5px 9px;
}}
QMessageBox {{
    background-color: {c.bg_elev};
}}
QMessageBox QLabel {{
    background: transparent;
    color: {c.fg};
}}
QCheckBox, QRadioButton, QGroupBox, QLabel {{
    background: transparent;
    color: {c.fg};
}}
QGroupBox {{
    border: 1px solid {c.border};
    border-radius: {c.radius_md};
    margin-top: 12px;
    padding-top: 10px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: {c.fg_muted};
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 15px;
    height: 15px;
}}
QProgressBar {{
    background-color: {c.bg_sunken};
    border: 1px solid {c.border};
    border-radius: {c.radius_sm};
    text-align: center;
    color: {c.fg};
}}
QProgressBar::chunk {{
    background-color: {c.accent};
    border-radius: {c.radius_sm};
}}
"""


# --------------------------------------------------------------------------
# Saída 3: QPalette
# --------------------------------------------------------------------------

def qt_palette(theme: str) -> Any:
    """Paleta do Qt, para o que o QSS não alcança.

    O QSS cobre os widgets que declaramos, mas não coisas desenhadas pelo
    próprio Qt — texto desabilitado, seleção em widgets nativos, a cor de
    destaque usada por alguns controles internos.
    """
    from PyQt6.QtGui import QColor, QPalette

    c = colors(theme)
    palette = QPalette()

    def set_color(role: Any, value: str) -> None:
        palette.setColor(role, QColor(value))

    set_color(QPalette.ColorRole.Window, c.bg)
    set_color(QPalette.ColorRole.WindowText, c.fg)
    set_color(QPalette.ColorRole.Base, c.bg_sunken)
    set_color(QPalette.ColorRole.AlternateBase, c.bg_elev)
    set_color(QPalette.ColorRole.Text, c.fg)
    set_color(QPalette.ColorRole.Button, c.bg_elev)
    set_color(QPalette.ColorRole.ButtonText, c.fg)
    set_color(QPalette.ColorRole.BrightText, c.danger)
    set_color(QPalette.ColorRole.ToolTipBase, c.toast_bg)
    set_color(QPalette.ColorRole.ToolTipText, c.toast_fg)
    set_color(QPalette.ColorRole.Highlight, c.selection_bg)
    set_color(QPalette.ColorRole.HighlightedText, c.selection_fg)
    set_color(QPalette.ColorRole.Link, c.accent)
    set_color(QPalette.ColorRole.PlaceholderText, c.fg_subtle)

    disabled = QPalette.ColorGroup.Disabled
    palette.setColor(disabled, QPalette.ColorRole.WindowText, QColor(c.fg_disabled))
    palette.setColor(disabled, QPalette.ColorRole.Text, QColor(c.fg_disabled))
    palette.setColor(disabled, QPalette.ColorRole.ButtonText, QColor(c.fg_disabled))

    return palette


# --------------------------------------------------------------------------
# Aplicação
# --------------------------------------------------------------------------

def apply_app_theme(app: Any, theme: str) -> str:
    """Aplica o tema em toda a interface. Devolve o tema efetivamente usado.

    ``Fusion`` é obrigatório aqui: o estilo nativo do Windows ignora boa parte
    do QSS, e sem ele os menus e a barra de ferramentas continuariam claros num
    tema escuro — que era justamente o defeito relatado.
    """
    palette_name = theme if theme in THEMES else DEFAULT_THEME

    app.setStyle("Fusion")
    app.setPalette(qt_palette(palette_name))
    app.setStyleSheet(qt_stylesheet(palette_name))
    return palette_name


def as_dict(theme: str) -> dict[str, str]:
    """Paleta como dicionário simples. Usado pelos testes e pelo gerador de CSS."""
    return asdict(colors(theme))
