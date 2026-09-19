"""Janela principal: abas, sidebar, preview compartilhado e menus.

Sobre o preview único: cada ``QWebEngineView`` traz um compositor próprio, e um
por aba faria a memória crescer rápido demais. Como só uma aba aparece por vez,
existe **um** preview, e trocar de aba troca o conteúdo dele. A posição de
leitura de cada documento é guardada na própria aba e restaurada na volta.

A sincronia de scroll é bidirecional e protegida por ``_syncing``: sem essa
trava, rolar o preview move o editor, cujo movimento reporta de volta ao
preview, num eco infinito.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QEvent, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QAction, QActionGroup, QCloseEvent, QDesktopServices, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QTextCursor

from edgemd import APP_NAME, __version__, icon_shapes
from edgemd.config import DEFAULT_VIEW_MODE, AppConfig, editing_available
from edgemd.shell import reveal_in_file_manager
from edgemd.editor_tab import FILE_FILTER, EditorTab
from edgemd.emoji_picker import EmojiPicker
from edgemd.image_insert import FILE_FILTER as IMAGE_FILE_FILTER
from edgemd.image_insert import is_inside, prepare_image
from edgemd.insert_dialogs import ImageDialog, LinkDialog
from edgemd.export import PdfExporter, export_html
from edgemd.icons import action_icon, app_icon, clear_action_cache, dot_badge_icon, tray_icon
from edgemd.mode_bar import ModeBar
from edgemd.paths import is_frozen
from edgemd.preview import PreviewView
from edgemd.render import LARGE_FILE_BYTES, MarkdownRenderer
from edgemd.safety import guarded_slot
from edgemd.sidebar import Sidebar
from edgemd.theme import apply_app_theme, colors as theme_colors, system_theme
from edgemd.tray import TrayIcon

log = logging.getLogger(__name__)

VIEW_MODE_LABELS = {
    "preview": "Somente preview",
    "split": "Editor e preview",
    "editor": "Somente editor",
}

#: Modo com que o app abre. Leitura primeiro; edição por um clique na faixa.
#: Definido em ``config`` para poder ser verificado sem instanciar a janela —
#: reexportado aqui porque é o módulo que os chamadores já importam.
__all__ = ["MainWindow", "DEFAULT_VIEW_MODE"]


def _theme_change_event_types() -> frozenset:
    """Tipos de evento que sinalizam troca de tema do sistema.

    O PyQt6 desta versão não expõe ``QEvent.Type.ThemeChange`` (que existe no
    Qt 6.5+), então montamos o conjunto por introspecção em vez de fixar um
    nome que pode não existir. ``ApplicationPaletteChange`` é o que o Qt emite
    quando o Windows troca entre claro e escuro.
    """
    names = ("ThemeChange", "ApplicationThemeChange", "ApplicationPaletteChange")
    found = set()
    for name in names:
        value = getattr(QEvent.Type, name, None)
        if value is not None:
            found.add(value)
    return frozenset(found)


_THEME_CHANGE_EVENTS = _theme_change_event_types()

#: Conteúdo mostrado quando não há nenhuma aba aberta.
EMPTY_STATE = """<!DOCTYPE html>
<html lang="pt-BR" data-theme="dark"><head><meta charset="utf-8">
<style>
  html, body { height: 100%%; margin: 0; }
  body {
    display: flex; align-items: center; justify-content: center;
    background: %(bg)s; color: %(fg)s;
    font-family: "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif;
    text-align: center; user-select: none;
  }
  .box { max-width: 30rem; padding: 2rem; }
  h1 { font-size: 1.35rem; font-weight: 600; margin: 0 0 .6rem; letter-spacing: -.01em; }
  p { margin: .35rem 0; color: %(muted)s; font-size: .92rem; line-height: 1.6; }
  kbd {
    font-family: Consolas, monospace; font-size: .82em;
    background: %(kbd_bg)s; border: 1px solid %(border)s;
    border-radius: 4px; padding: .1em .4em;
  }
</style></head>
<body><div class="box">
  <h1>Nenhum arquivo aberto</h1>
  <p>Arraste um <kbd>.md</kbd> para cá, ou use <kbd>Ctrl+O</kbd> para abrir
     e <kbd>Ctrl+N</kbd> para criar um novo.</p>
  <p>Para navegar por uma pasta inteira, use <kbd>Ctrl+Shift+O</kbd>.</p>
</div></body></html>
"""

EMPTY_STATE_COLORS = {
    "dark": {
        "bg": "#16181d", "fg": "#e4e7ee", "muted": "#a2a9b8",
        "kbd_bg": "#23272f", "border": "#31363f",
    },
    "light": {
        "bg": "#fdfdfc", "fg": "#1f2328", "muted": "#59606d",
        "kbd_bg": "#f0f2f5", "border": "#dfe3e8",
    },
}


class MainWindow(QMainWindow):
    """Janela principal do aplicativo."""

    def __init__(
        self,
        config: AppConfig,
        renderer: MarkdownRenderer,
        *,
        start_hidden: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.renderer = renderer

        self._syncing = False
        self._force_close = False
        self._pdf_exporter: PdfExporter | None = None
        self._external_check_timer: QTimer | None = None
        self._pending_keep_line: int | None = None
        self._current_theme = "dark"
        #: Seletor de emoji, criado na primeira vez que for usado.
        self._emoji_picker: EmojiPicker | None = None
        #: Modo de exibição da sessão. Sempre começa em leitura: o app é um
        #: leitor, e abrir um .md no modo de edição contraria essa expectativa.
        self._view_mode = DEFAULT_VIEW_MODE

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setAcceptDrops(True)
        self.setMinimumSize(720, 480)

        # Os temporizadores vêm antes da interface: _apply_view_mode, chamado
        # durante a montagem dos widgets, agenda uma renderização.
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render_now)

        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._sync_preview_to_cursor)

        # As ações vêm antes da interface: _apply_view_mode marca a ação do
        # modo ativo como selecionada.
        self._build_actions()
        self._build_ui()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self._build_tray()

        self._restore_window_state()
        self._apply_theme(self._initial_theme(), persist=False)
        self._update_actions()
        self._start_external_watch()

        if start_hidden:
            self.hide()

    # ==================================================================
    # Construção da interface
    # ==================================================================
    def _build_ui(self) -> None:
        self.sidebar = Sidebar(self)
        self.sidebar.fileActivated.connect(self.open_path)

        self.tabs = QTabWidget(self)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.preview = PreviewView(theme=self._initial_theme(), parent=self)
        self.preview.fileRequested.connect(self.open_path)
        self.preview.externalRequested.connect(self._open_external)
        self.preview.scrolled.connect(self._on_preview_scrolled)
        # Duplo clique no documento é o atalho natural para "quero mexer nisto".
        self.preview.editRequested.connect(self.enter_edit_mode)

        # Faixa acima do preview com o nome do arquivo e o botão de modo. É o
        # componente que o usuário clica para entrar e sair da edição.
        self.mode_bar = ModeBar(self)
        self.mode_bar.editRequested.connect(self.enter_edit_mode)
        self.mode_bar.readRequested.connect(self.enter_read_mode)

        preview_pane = QWidget(self)
        preview_layout = QVBoxLayout(preview_pane)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)
        preview_layout.addWidget(self.mode_bar)
        preview_layout.addWidget(self.preview, 1)

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.content_splitter.addWidget(self.tabs)
        self.content_splitter.addWidget(preview_pane)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 1)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setSizes([520, 520])

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.main_splitter.addWidget(self.sidebar)
        self.main_splitter.addWidget(self.content_splitter)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([260, 1000])
        self.setCentralWidget(self.main_splitter)

        self._apply_view_mode(self._view_mode)
        self.sidebar.setVisible(self.config.sidebar_visible)

        self.setAcceptDrops(True)

    def _build_actions(self) -> None:
        #: Ação -> nome do ícone. Alimenta :meth:`_refresh_action_icons` na
        #: troca de tema, já que a cor fica gravada no desenho.
        self._icon_actions: dict[QAction, str] = {}

        def make(
            text: str,
            shortcut: str | None,
            slot,
            *,
            tip: str = "",
            icon: str | None = None,
        ) -> QAction:
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.setStatusTip(tip or text)
            action.setToolTip(tip or text)
            action.triggered.connect(slot)
            if icon:
                if icon not in icon_shapes.ICONS:
                    # Falha alto e cedo: um nome errado daria um botão invisível
                    # na barra, e isso passa fácil numa revisão de código.
                    raise ValueError(
                        f"ícone '{icon}' não existe em icon_shapes.ICONS "
                        f"(ação: {text})"
                    )
                self._icon_actions[action] = icon
            return action

        self.action_new = make(
            "Novo", "Ctrl+N", self.new_file,
            tip="Criar um documento novo", icon="new",
        )
        self.action_open = make(
            "Abrir…", "Ctrl+O", self.open_file_dialog,
            tip="Abrir um arquivo Markdown", icon="open",
        )
        self.action_open_folder = make(
            "Abrir pasta…", "Ctrl+Shift+O", self.open_folder_dialog,
            tip="Navegar por uma pasta de notas", icon="open-folder",
        )
        self.action_save = make(
            "Salvar", "Ctrl+S", self.save_current,
            tip="Salvar o documento atual", icon="save",
        )
        self.action_save_as = make(
            "Salvar como…", "Ctrl+Shift+S", self.save_current_as,
            tip="Salvar com outro nome", icon="save-as",
        )
        self.action_export_html = make(
            "Exportar para HTML…", "Ctrl+E", self.export_current_html,
            tip="Gerar um HTML autônomo, com imagens embutidas", icon="export-html",
        )
        self.action_export_pdf = make(
            "Exportar para PDF…", "Ctrl+Shift+E", self.export_current_pdf,
            tip="Gerar um PDF paginado", icon="export-pdf",
        )
        self.action_close_tab = make(
            "Fechar aba", "Ctrl+W", lambda: self.close_tab(self.tabs.currentIndex()),
            tip="Fechar a aba atual", icon="close",
        )
        self.action_close_all = make("Fechar todas as abas", "Ctrl+Shift+W", self.close_all_tabs)
        self.action_quit = make("Sair", "Ctrl+Q", self.quit_application, icon="quit")

        self.action_undo = make("Desfazer", "Ctrl+Z", lambda: self._editor_call("undo"), icon="undo")
        self.action_redo = make("Refazer", "Ctrl+Y", lambda: self._editor_call("redo"), icon="redo")
        self.action_cut = make("Recortar", "Ctrl+X", lambda: self._editor_call("cut"), icon="cut")
        self.action_copy = make("Copiar", "Ctrl+C", lambda: self._editor_call("copy"), icon="copy")
        self.action_paste = make("Colar", "Ctrl+V", lambda: self._editor_call("paste"), icon="paste")
        self.action_select_all = make(
            "Selecionar tudo", "Ctrl+A", lambda: self._editor_call("select_all"),
            icon="select-all",
        )
        # Localizar e substituir só fazem sentido com o editor à vista: no modo
        # de leitura não há o que procurar nem trocar. As ações nascem
        # desabilitadas, e _update_actions cuida disso a cada troca de modo.
        self.action_find = make(
            "Localizar…", "Ctrl+F", self.open_find,
            tip="Localizar no documento (só na edição)", icon="find",
        )
        self.action_find_next = make(
            "Localizar próxima", "F3", lambda: self._search_step(1),
            tip="Ir para a próxima ocorrência", icon="find-next",
        )
        self.action_find_previous = make(
            "Localizar anterior", "Shift+F3", lambda: self._search_step(-1),
            tip="Ir para a ocorrência anterior", icon="find-previous",
        )
        self.action_replace = make(
            "Substituir…", "Ctrl+H", self.open_replace,
            tip="Localizar e substituir (só na edição)", icon="replace",
        )

        self.action_bold = make(
            "Negrito", "Ctrl+B", lambda: self._wrap("**", "**", "negrito"),
            tip="Envolver em **negrito**", icon="bold",
        )
        self.action_italic = make(
            "Itálico", "Ctrl+I", lambda: self._wrap("*", "*", "itálico"),
            tip="Envolver em *itálico*", icon="italic",
        )
        self.action_strike = make(
            "Riscado", "Ctrl+Shift+X", lambda: self._wrap("~~", "~~", "riscado"),
            tip="Envolver em ~~riscado~~", icon="strikethrough",
        )
        self.action_code = make(
            "Código", "Ctrl+`", lambda: self._wrap("`", "`", "código"),
            tip="Envolver em `código`", icon="code-inline",
        )
        self.action_link = make(
            "Link", "Ctrl+K", self.insert_link,
            tip="Inserir um link", icon="link",
        )
        self.action_image = make(
            "Imagem…", "Ctrl+Shift+I", self.insert_image,
            tip="Inserir uma imagem do disco", icon="image",
        )
        self.action_emoji = make(
            "Emoji…", "Ctrl+.", self.insert_emoji,
            tip="Escolher um emoji para inserir", icon="emoji",
        )
        self.action_code_block = make(
            "Bloco de código", "Ctrl+Shift+C", self._insert_code_block,
            tip="Inserir um bloco de código", icon="code-block",
        )
        self.action_table = make(
            "Tabela", "Ctrl+Shift+T", self._insert_table,
            tip="Inserir uma tabela", icon="table",
        )
        self.action_h1 = make("Título 1", "Ctrl+1", lambda: self._prefix("# "), icon="h1")
        self.action_h2 = make("Título 2", "Ctrl+2", lambda: self._prefix("## "), icon="h2")
        self.action_h3 = make("Título 3", "Ctrl+3", lambda: self._prefix("### "), icon="h3")
        self.action_quote = make(
            "Citação", "Ctrl+Shift+.", lambda: self._prefix("> "),
            tip="Transformar a linha em citação", icon="quote",
        )
        self.action_bullet = make(
            "Lista com marcadores", "Ctrl+Shift+8", lambda: self._prefix("- "), icon="list-bullet",
        )
        self.action_numbered = make(
            "Lista numerada", "Ctrl+Shift+7", lambda: self._prefix("1. "), icon="list-number",
        )
        self.action_task = make(
            "Item de tarefa", "Ctrl+Shift+9", lambda: self._prefix("- [ ] "), icon="task",
        )
        self.action_hr = make(
            "Linha horizontal", None, lambda: self._insert_text("\n---\n"), icon="hr",
        )

        self.action_view_preview = make(
            "Somente leitura", "Ctrl+Shift+P", lambda: self.set_view_mode("preview"),
            tip="Ver apenas o documento renderizado", icon="read",
        )
        self.action_view_split = make(
            "Editor e preview", "Ctrl+Shift+D", lambda: self.set_view_mode("split"),
            tip="Editar com o resultado ao lado", icon="split",
        )
        # Ctrl+Shift+E já é a exportação para PDF; o modo editor usa Ctrl+Shift+M.
        self.action_view_editor = make(
            "Somente editor", "Ctrl+Shift+M", lambda: self.set_view_mode("editor"),
            tip="Ver apenas o código Markdown", icon="editor-only",
        )

        self._view_group = QActionGroup(self)
        self._view_group.setExclusive(True)
        for action, mode in (
            (self.action_view_preview, "preview"),
            (self.action_view_split, "split"),
            (self.action_view_editor, "editor"),
        ):
            action.setCheckable(True)
            action.setData(mode)
            self._view_group.addAction(action)
        self._view_group.triggered.connect(
            lambda action: self.set_view_mode(action.data())
        )

        self.action_theme_light = make("Tema claro", None, lambda: self.set_theme("light"))
        self.action_theme_dark = make("Tema escuro", None, lambda: self.set_theme("dark"))
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        for action in (self.action_theme_light, self.action_theme_dark):
            action.setCheckable(True)
            self._theme_group.addAction(action)
        self.action_toggle_theme = make(
            "Alternar tema", "Ctrl+T", self.toggle_theme,
            tip="Alternar entre tema claro e escuro", icon="theme",
        )

        self.action_sidebar = make(
            "Painel lateral", "Ctrl+L", self.toggle_sidebar,
            tip="Mostrar ou ocultar a árvore de arquivos", icon="sidebar",
        )
        self.action_sidebar.setCheckable(True)
        self.action_sidebar.setChecked(self.config.sidebar_visible)

        self.action_line_numbers = make(
            "Números de linha", None, self.toggle_line_numbers, icon="line-numbers",
        )
        self.action_line_numbers.setCheckable(True)
        self.action_line_numbers.setChecked(self.config.show_line_numbers)

        self.action_word_wrap = make(
            "Quebra de linha automática", None, self.toggle_word_wrap, icon="word-wrap",
        )
        self.action_word_wrap.setCheckable(True)
        self.action_word_wrap.setChecked(self.config.word_wrap)

        self.action_scroll_sync = make(
            "Sincronizar rolagem", None, self.toggle_scroll_sync, icon="scroll-sync",
        )
        self.action_scroll_sync.setCheckable(True)
        self.action_scroll_sync.setChecked(self.config.scroll_sync)

        self.action_zoom_in = make(
            "Aumentar fonte", "Ctrl++", lambda: self._zoom(1), icon="zoom-in",
        )
        self.action_zoom_out = make(
            "Diminuir fonte", "Ctrl+-", lambda: self._zoom(-1), icon="zoom-out",
        )

        self.action_register = make(
            "Associar arquivos .md a este app…", None, self.register_association,
            tip="Faz o clique duplo num .md abrir aqui (sem precisar de admin)",
            icon="association",
        )
        self.action_unregister = make(
            "Desfazer associação", None, self.unregister_association, icon="unlink",
        )
        self.action_reveal_config = make(
            "Abrir pasta de notas no Explorer", None, self._reveal_folder, icon="reveal",
        )
        self.action_render_now = make(
            "Atualizar preview agora", "F5", self._render_now,
            tip="Redesenhar o preview (útil em arquivos grandes, onde a "
                "atualização automática fica desligada)",
            icon="refresh",
        )
        self.action_toggle_button_text = make(
            "Mostrar texto nos botões", None, self.toggle_button_text,
            tip="Exibir o nome de cada botão abaixo do ícone",
        )
        self.action_toggle_button_text.setCheckable(True)
        self.action_toggle_button_text.setChecked(self.config.toolbar_show_text)
        self.action_about = make("Sobre", None, self.show_about, icon="info")

    def _build_menus(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&Arquivo")
        file_menu.addAction(self.action_new)
        file_menu.addAction(self.action_open)
        file_menu.addAction(self.action_open_folder)
        file_menu.addSeparator()

        self._recent_menu = file_menu.addMenu("Abrir recente")
        self._rebuild_recent_menu()

        file_menu.addSeparator()
        file_menu.addAction(self.action_save)
        file_menu.addAction(self.action_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self.action_export_html)
        file_menu.addAction(self.action_export_pdf)
        file_menu.addSeparator()
        file_menu.addAction(self.action_close_tab)
        file_menu.addAction(self.action_close_all)
        file_menu.addSeparator()
        file_menu.addAction(self.action_quit)

        edit_menu = bar.addMenu("&Editar")
        edit_menu.addAction(self.action_undo)
        edit_menu.addAction(self.action_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_cut)
        edit_menu.addAction(self.action_copy)
        edit_menu.addAction(self.action_paste)
        edit_menu.addAction(self.action_select_all)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_find)
        edit_menu.addAction(self.action_find_next)
        edit_menu.addAction(self.action_find_previous)
        edit_menu.addAction(self.action_replace)

        insert_menu = bar.addMenu("&Inserir")
        insert_menu.addAction(self.action_bold)
        insert_menu.addAction(self.action_italic)
        insert_menu.addAction(self.action_strike)
        insert_menu.addAction(self.action_code)
        insert_menu.addAction(self.action_link)
        insert_menu.addAction(self.action_image)
        insert_menu.addAction(self.action_emoji)
        insert_menu.addSeparator()
        insert_menu.addAction(self.action_h1)
        insert_menu.addAction(self.action_h2)
        insert_menu.addAction(self.action_h3)
        insert_menu.addSeparator()
        insert_menu.addAction(self.action_bullet)
        insert_menu.addAction(self.action_numbered)
        insert_menu.addAction(self.action_task)
        insert_menu.addAction(self.action_quote)
        insert_menu.addSeparator()
        insert_menu.addAction(self.action_code_block)
        insert_menu.addAction(self.action_table)
        insert_menu.addAction(self.action_hr)

        view_menu = bar.addMenu("E&xibir")
        view_menu.addAction(self.action_view_preview)
        view_menu.addAction(self.action_view_split)
        view_menu.addAction(self.action_view_editor)
        view_menu.addSeparator()
        view_menu.addAction(self.action_toggle_theme)
        view_menu.addAction(self.action_theme_light)
        view_menu.addAction(self.action_theme_dark)
        view_menu.addSeparator()
        view_menu.addAction(self.action_sidebar)
        view_menu.addAction(self.action_line_numbers)
        view_menu.addAction(self.action_word_wrap)
        view_menu.addAction(self.action_scroll_sync)
        view_menu.addSeparator()
        view_menu.addAction(self.action_toggle_button_text)
        view_menu.addSeparator()
        view_menu.addAction(self.action_zoom_in)
        view_menu.addAction(self.action_zoom_out)

        tools_menu = bar.addMenu("F&erramentas")
        tools_menu.addAction(self.action_register)
        tools_menu.addAction(self.action_unregister)
        tools_menu.addSeparator()
        tools_menu.addAction(self.action_reveal_config)

        help_menu = bar.addMenu("A&juda")
        help_menu.addAction(self.action_about)

    def _build_toolbar(self) -> None:
        """Monta a barra de ferramentas com ícones, agrupados por assunto.

        A ordem segue o fluxo de trabalho — arquivo, modo de exibição, edição,
        formatação, saída, aparência — em vez de seguir a ordem dos menus. É o
        que uma barra de ferramentas do Office faz: os separadores criam grupos
        que se leem de relance.
        """
        toolbar = QToolBar("Principal", self)
        # saveState()/restoreState() identificam barras e docks pelo objectName.
        # Sem ele o Qt avisa "'objectName' not set for QToolBar" e simplesmente
        # não persiste o estado da barra entre execuções.
        toolbar.setObjectName("mainToolBar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        self._apply_toolbar_text_style(toolbar)
        self.toolbar = toolbar

        groups = [
            [self.action_new, self.action_open, self.action_open_folder,
             self.action_save, self.action_save_as],
            [self.action_view_preview, self.action_view_split, self.action_view_editor],
            [self.action_undo, self.action_redo,
             self.action_cut, self.action_copy, self.action_paste],
            [self.action_bold, self.action_italic, self.action_strike,
             self.action_code, self.action_link, self.action_image, self.action_emoji],
            [self.action_h1, self.action_h2, self.action_h3],
            [self.action_bullet, self.action_numbered, self.action_task,
             self.action_quote],
            [self.action_code_block, self.action_table, self.action_hr],
            [self.action_export_html, self.action_export_pdf],
            [self.action_toggle_theme, self.action_sidebar],
        ]

        for index, group in enumerate(groups):
            if index:
                toolbar.addSeparator()
            for action in group:
                toolbar.addAction(action)

        self.addToolBar(toolbar)

    def _apply_toolbar_text_style(self, toolbar: QToolBar) -> None:
        """Aplica o estilo de rótulo escolhido pelo usuário."""
        toolbar.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextUnderIcon
            if self.config.toolbar_show_text
            else Qt.ToolButtonStyle.ToolButtonIconOnly
        )

    def toggle_button_text(self) -> None:
        """Alterna entre só ícone e ícone com o nome embaixo."""
        show_text = self.action_toggle_button_text.isChecked()
        self.config.toolbar_show_text = show_text
        self._apply_toolbar_text_style(self.toolbar)

    def _build_statusbar(self) -> None:
        self._status_message = QLabel("")
        self._status_position = QLabel("")
        self._status_counts = QLabel("")
        self._status_encoding = QLabel("")

        for label in (self._status_position, self._status_counts, self._status_encoding):
            label.setMinimumWidth(90)

        bar = self.statusBar()
        bar.addWidget(self._status_message, 1)
        bar.addPermanentWidget(self._status_position)
        bar.addPermanentWidget(self._status_counts)
        bar.addPermanentWidget(self._status_encoding)

    def _build_tray(self) -> None:
        # A bandeja usa a arte sem a assinatura: em 16 px o texto do ícone
        # completo vira mancha cinza e some.
        self.tray = TrayIcon(tray_icon(), self)
        self.tray.set_icons(tray_icon(), dot_badge_icon(tray_icon()))
        self.tray.showRequested.connect(self.show_from_tray)
        self.tray.hideRequested.connect(self.hide)
        self.tray.newFileRequested.connect(self._tray_new_file)
        self.tray.openFileRequested.connect(self.open_file_dialog)
        self.tray.openFolderRequested.connect(self.open_folder_dialog)
        self.tray.fileRequested.connect(self.open_path)
        self.tray.quitRequested.connect(self.quit_application)
        self.tray.update_recent(self.config.recent_files)

    # ==================================================================
    # Estado / abas
    # ==================================================================
    @property
    def current_tab(self) -> EditorTab | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, EditorTab) else None

    def _tabs(self) -> list[EditorTab]:
        return [
            self.tabs.widget(i)
            for i in range(self.tabs.count())
            if isinstance(self.tabs.widget(i), EditorTab)
        ]

    def _next_untitled_label(self) -> str:
        """Rótulo livre para um documento novo ("Sem título", "Sem título 2", ...)."""
        used = {tab.display_name.rstrip(" •") for tab in self._tabs()}
        if "Sem título" not in used:
            return "Sem título"
        index = 2
        while f"Sem título {index}" in used:
            index += 1
        return f"Sem título {index}"

    def new_file(self) -> None:
        tab = EditorTab(theme=self._theme, parent=self)
        tab.set_untitled_label(self._next_untitled_label())
        self._add_tab(tab)
        # Conteúdo inicial poupa o usuário de digitar o título. Marcamos como
        # limpo para que uma aba recém-criada não peça confirmação ao fechar.
        tab.editor.setPlainText("# \n\n")
        tab.editor.document().setModified(False)
        cursor = tab.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        tab.editor.setTextCursor(cursor)
        tab.editor.setFocus()

    def _add_tab(self, tab: EditorTab, *, activate: bool = True) -> None:
        tab.dirtyChanged.connect(self._on_tab_dirty)
        tab.titleChanged.connect(lambda _title, t=tab: self._on_tab_title(t))
        tab.contentsChanged.connect(self._on_contents_changed)
        tab.cursorLineChanged.connect(self._on_cursor_line)
        tab.undoAvailableChanged.connect(lambda _v: self._update_actions())
        tab.redoAvailableChanged.connect(lambda _v: self._update_actions())
        tab.externallyModified.connect(lambda t=tab: self._on_external_change(t))

        tab.editor.apply_theme(self._theme)
        tab.editor.set_line_numbers_visible(self.config.show_line_numbers)
        tab.editor.set_word_wrap(self.config.word_wrap)
        tab.editor.set_font_size(self.config.editor_font_size)

        index = self.tabs.addTab(tab, tab.display_name)
        self.tabs.setTabToolTip(index, tab.absolute_title)
        if activate:
            self.tabs.setCurrentIndex(index)

    def _on_tab_changed(self, index: int) -> None:
        tab = self.current_tab
        if tab is None:
            self._show_empty_state()
            self._update_actions()
            return

        # Espera a UI assentar antes de rolar: a geometria do preview só é
        # confiável depois que ele tem tamanho real.
        self._schedule_render(keep_line=tab.last_preview_line)
        self._update_status()
        self._update_actions()
        self._update_window_title()

    def _on_tab_dirty(self, dirty: bool) -> None:
        any_dirty = any(tab.is_dirty for tab in self._tabs())
        self.tray.set_dirty(any_dirty)
        self._update_window_title()
        tab = self.current_tab
        if tab is not None:
            self.mode_bar.set_document_name(tab.absolute_title, dirty=tab.is_dirty)

    def _on_tab_title(self, tab: EditorTab) -> None:
        index = self.tabs.indexOf(tab)
        if index >= 0:
            self.tabs.setTabText(index, tab.display_name)
            self.tabs.setTabToolTip(index, tab.absolute_title)
        self._update_window_title()

    def _on_contents_changed(self) -> None:
        self._schedule_render()
        self._update_status()

    def _on_cursor_line(self, line: int) -> None:
        tab = self.current_tab
        if tab is not None:
            tab.last_editor_line = line
        self._update_position()
        if self.config.scroll_sync and self.preview.isVisible():
            self._sync_timer.start(120)

    # ==================================================================
    # Renderização
    # ==================================================================
    def _schedule_render(self, keep_line: int | None = None) -> None:
        if keep_line is not None:
            self._pending_keep_line = keep_line
        self._render_timer.start(self.config.render_delay_ms)

    def _render_now(self) -> None:
        tab = self.current_tab
        if tab is None:
            self._show_empty_state()
            return

        text = tab.editor.toPlainText()
        keep_line = self._pending_keep_line
        self._pending_keep_line = None

        if keep_line is None:
            keep_line = tab.last_preview_line

        # Arquivos muito grandes travam o Chromium; avisamos e seguimos sem
        # atualizar o preview automaticamente.
        if len(text.encode("utf-8", errors="ignore")) > LARGE_FILE_BYTES:
            self._status_message.setText(
                "Arquivo grande: use Exibir → atualizar para renderizar sob demanda."
            )
            return

        previous_keep = keep_line
        try:
            document = self.renderer.render_document(
                text,
                doc_path=tab.path,
                title=tab.display_name,
                show_mermaid=self.config.show_mermaid,
                show_math=self.config.show_math,
                theme=self._theme,
            )
        except Exception as exc:  # noqa: BLE001 - render nunca deve derrubar o app
            log.exception("Falha ao renderizar o documento.")
            self._status_message.setText(f"Erro ao renderizar: {exc}")
            return

        self.preview.set_document(document, keep_line=previous_keep)
        self._status_message.setText("")
        self._current_rendered_tab = tab

    def _show_empty_state(self) -> None:
        colors = EMPTY_STATE_COLORS.get(self._theme, EMPTY_STATE_COLORS["dark"])
        self.preview.page().setHtml(EMPTY_STATE % colors, QUrl("about:blank"))
        self._status_message.setText("")
        self._status_position.setText("")
        self._status_counts.setText("")
        self._status_encoding.setText("")

    def _sync_preview_to_cursor(self) -> None:
        tab = self.current_tab
        if tab is None or self._syncing:
            return
        self._syncing = True
        try:
            self.preview.scroll_to_line(tab.last_editor_line)
        finally:
            # Libera no próximo ciclo do laço de eventos, depois que o JS
            # respondeu, para não ecoar o próprio movimento.
            QTimer.singleShot(160, self._release_sync)

    def _release_sync(self) -> None:
        self._syncing = False

    def _on_preview_scrolled(self, line: int) -> None:
        tab = self.current_tab
        if tab is None:
            return
        tab.last_preview_line = line
        if not self.config.scroll_sync or self._syncing:
            return
        if not self.tabs.isVisible():
            return
        self._syncing = True
        try:
            tab.editor.scroll_to_line(line)
        finally:
            QTimer.singleShot(160, self._release_sync)

    # ==================================================================
    # Arquivos
    # ==================================================================
    def open_file_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Abrir Markdown", str(self.config.last_directory), FILE_FILTER
        )
        if paths:
            self.config.last_directory = Path(paths[0]).parent
            self.open_paths(paths)

    def open_folder_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Abrir pasta de notas", str(self.config.last_directory)
        )
        if not folder:
            return
        self.sidebar.set_root(folder)
        self.sidebar.setVisible(True)
        self.action_sidebar.setChecked(True)
        self.config.sidebar_visible = True
        self.config.last_directory = folder

    def open_path(self, path: str | Path) -> None:
        self.open_paths([path])

    def open_paths(self, paths: list[str | Path]) -> None:
        """Abre um ou mais arquivos, reaproveitando abas já abertas."""
        failures: list[str] = []
        last_tab: EditorTab | None = None

        for raw in paths:
            path = Path(raw)
            if not path.is_file():
                failures.append(str(path))
                continue

            resolved = str(path.resolve())

            # Já aberto? Só ativa a aba, sem duplicar.
            existing = next(
                (tab for tab in self._tabs() if tab.path and str(tab.path) == resolved),
                None,
            )
            if existing is not None:
                self.tabs.setCurrentWidget(existing)
                last_tab = existing
                continue

            tab = EditorTab(path, theme=self._theme, parent=self)
            if tab.path is None:
                failures.append(str(path))
                continue
            self._add_tab(tab)
            self.config.add_recent_file(resolved)
            last_tab = tab

        if failures:
            QMessageBox.warning(
                self,
                "Não foi possível abrir",
                "Estes arquivos não puderam ser lidos:\n\n" + "\n".join(failures[:10]),
            )

        if last_tab is not None:
            self.tabs.setCurrentWidget(last_tab)
            last_tab.editor.setFocus()
            if last_tab.path is not None:
                self.sidebar.select_path(last_tab.path)

        self._rebuild_recent_menu()
        self.tray.update_recent(self.config.recent_files)

    def save_current(self) -> bool:
        tab = self.current_tab
        if tab is None:
            return False
        if tab.path is None:
            return self.save_current_as()
        if not tab.save():
            QMessageBox.critical(
                self, "Não foi possível salvar",
                f"Falha ao gravar:\n{tab.path}\n\n"
                "Verifique se o arquivo não está somente-leitura ou aberto "
                "em outro programa.",
            )
            return False
        self._update_status()
        self._update_actions()
        return True

    def save_current_as(self) -> bool:
        tab = self.current_tab
        if tab is None:
            return False

        suggested = str(tab.path) if tab.path else str(
            self.config.last_directory / "nota.md"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Salvar como", suggested, FILE_FILTER
        )
        if not path:
            return False

        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".md")

        if not tab.save_as(target):
            QMessageBox.critical(
                self, "Não foi possível salvar", f"Falha ao gravar:\n{target}"
            )
            return False

        self.config.add_recent_file(target)
        self.config.last_directory = target.parent
        index = self.tabs.indexOf(tab)
        if index >= 0:
            self.tabs.setTabText(index, tab.display_name)
            self.tabs.setTabToolTip(index, tab.absolute_title)
        self._rebuild_recent_menu()
        self.tray.update_recent(self.config.recent_files)
        self._update_window_title()
        self._update_actions()
        return True

    def close_tab(self, index: int) -> bool:
        """Fecha a aba, pedindo confirmação se houver alterações."""
        widget = self.tabs.widget(index)
        if not isinstance(widget, EditorTab):
            return False

        if widget.is_dirty and not self._confirm_discard(widget):
            return False

        self.tabs.removeTab(index)
        widget.deleteLater()

        if self.tabs.count() == 0:
            self._show_empty_state()
        self._update_actions()
        self._update_window_title()
        return True

    def _confirm_discard(self, tab: EditorTab) -> bool:
        """True se pode descartar; False se o usuário cancelou."""
        answer = QMessageBox.question(
            self,
            "Alterações não salvas",
            f"Salvar as alterações em “{tab.display_name.rstrip(' •')}”?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )

        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Discard:
            return True

        # Save: se for documento novo, o usuário ainda precisa escolher o nome.
        self.tabs.setCurrentWidget(tab)
        return self.save_current()

    def close_all_tabs(self) -> bool:
        """Fecha todas as abas. False se o usuário cancelou em alguma."""
        for index in range(self.tabs.count() - 1, -1, -1):
            if not self.close_tab(index):
                return False
        return True

    def _open_external(self, url: str) -> None:
        """Abre um link externo no navegador padrão."""
        QDesktopServices.openUrl(QUrl(url))

    def _reveal_folder(self) -> None:
        folder = self.sidebar.root or self.config.last_directory
        if folder and Path(folder).is_dir():
            self.sidebar.reveal_in_explorer(str(folder))

    # ==================================================================
    # Exportação
    # ==================================================================
    def export_current_html(self) -> None:
        tab = self.current_tab
        if tab is None:
            return

        base = tab.path.with_suffix(".html") if tab.path else self.config.last_directory / "nota.html"
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar HTML", str(base), "Página HTML (*.html);;Todos os arquivos (*)"
        )
        if not path:
            return

        try:
            result = export_html(
                self.renderer,
                tab.editor.toPlainText(),
                tab.path,
                path,
                theme=self._theme,
                show_mermaid=self.config.show_mermaid,
                show_math=self.config.show_math,
            )
        except OSError as exc:
            QMessageBox.critical(
                self, "Falha na exportação", f"Não foi possível gravar:\n{path}\n\n{exc}"
            )
            return
        except Exception as exc:  # noqa: BLE001 - export não pode derrubar o app
            log.exception("Falha ao exportar HTML.")
            QMessageBox.critical(
                self,
                "Falha na exportação",
                f"Ocorreu um erro ao gerar o HTML:\n\n{type(exc).__name__}: {exc}",
            )
            return

        detail = f"{result.size_label}"
        if result.embedded:
            detail += f", {result.embedded} imagem(ns) embutida(s)"
        if result.failed:
            detail += f", {result.failed} imagem(ns) não encontrada(s)"

        self.tray.notify("HTML exportado", f"{Path(result.target).name} — {detail}")
        self._status_message.setText(f"Exportado: {result.target}")

    @guarded_slot("Falha ao gerar PDF", "Não foi possível iniciar a geração do PDF.")
    def export_current_pdf(self) -> None:
        tab = self.current_tab
        if tab is None:
            return

        base = tab.path.with_suffix(".pdf") if tab.path else self.config.last_directory / "nota.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar PDF", str(base), "PDF (*.pdf);;Todos os arquivos (*)"
        )
        if not path:
            return

        self._status_message.setText("Gerando PDF…")

        # Uma exportação por vez: dois PdfExporter concorrentes disputariam o
        # mesmo caminho e o sinal de conclusão de um cancelaria o outro.
        if self._pdf_exporter is not None:
            QMessageBox.information(
                self,
                "Exportação em andamento",
                "Aguarde a exportação atual terminar.",
            )
            return

        exporter = PdfExporter(self)
        self._pdf_exporter = exporter
        exporter.finished.connect(self._on_pdf_finished)
        exporter.export(
            self.renderer,
            tab.editor.toPlainText(),
            tab.path,
            path,
            theme=self._theme,
            show_mermaid=self.config.show_mermaid,
            show_math=self.config.show_math,
        )

    @guarded_slot("Falha ao gerar PDF")
    def _on_pdf_finished(self, path: str, ok: bool) -> None:
        self._pdf_exporter = None
        if ok:
            self._status_message.setText(f"PDF gerado: {path}")
            self.tray.notify("PDF gerado", Path(path).name)
        else:
            self._status_message.setText("")
            QMessageBox.critical(
                self,
                "Falha ao gerar PDF",
                f"Não foi possível gerar o PDF em:\n{path or '(caminho vazio)'}",
            )

    # ==================================================================
    # Edição
    # ==================================================================
    def _editor_call(self, method: str) -> None:
        tab = self.current_tab
        if tab is None:
            return
        editor = tab.editor
        if method == "select_all":
            editor.selectAll()
        else:
            getattr(editor, method)()

    # ------------------------------------------------------------------
    # Busca
    # ------------------------------------------------------------------
    def open_find(self) -> None:
        """Abre a barra de localização no documento atual."""
        tab = self.current_tab
        if tab is None:
            return
        if not self._editing_available():
            self._tell_read_mode()
            return
        tab.open_search(with_replace=False)

    def open_replace(self) -> None:
        """Abre a barra já com o campo de substituição."""
        tab = self.current_tab
        if tab is None:
            return
        if not self._editing_available():
            self._tell_read_mode()
            return
        tab.open_search(with_replace=True)

    def _search_step(self, direction: int) -> None:
        """F3 e Shift+F3.

        Com a barra fechada, o atalho a abre em vez de não fazer nada — é o que
        se espera ao apertar F3 para repetir a última busca.
        """
        tab = self.current_tab
        if tab is None or not self._editing_available():
            return
        if not tab.is_searching:
            tab.open_search(with_replace=False)
            return
        tab.search.step(direction)

    def _editing_available(self) -> bool:
        """True quando o editor está à vista, ou seja, fora do modo de leitura."""
        return editing_available(self._view_mode)

    def _tell_read_mode(self) -> None:
        self._status_message.setText(
            "Localizar e substituir ficam disponíveis na edição — "
            "clique em Editar (Ctrl+Shift+D)."
        )
        QTimer.singleShot(4000, lambda: self._status_message.setText(""))

    def _close_search_on_all_tabs(self) -> None:
        """Fecha a barra de busca em todas as abas.

        Ao entrar no modo de leitura, deixar a barra aberta numa aba escondida
        faria o próximo ``Ctrl+F`` abrir algo que não está à vista.
        """
        for tab in self._tabs():
            tab.close_search()

    def _wrap(self, before: str, after: str, placeholder: str) -> None:
        tab = self.current_tab
        if tab is not None:
            tab.editor.insert_surround(before, after, placeholder)

    def _prefix(self, prefix: str) -> None:
        tab = self.current_tab
        if tab is not None:
            tab.editor.insert_line_prefix(prefix)

    # ------------------------------------------------------------------
    # Inserção de link, imagem e emoji
    # ------------------------------------------------------------------
    def insert_link(self) -> None:
        """Abre o diálogo de link, aproveitando a seleção como texto."""
        tab = self.current_tab
        if tab is None:
            return

        selecionado = tab.editor.textCursor().selectedText()
        # selectedText troca quebra de linha por U+2029; num rótulo de link isso
        # viraria um parágrafo, então descartamos seleções de várias linhas.
        texto_inicial = selecionado.replace("\u2029", "\n").strip()
        if "\n" in texto_inicial:
            texto_inicial = ""

        resposta = LinkDialog.ask(self, text=texto_inicial, url=self._clipboard_url())
        if resposta is None:
            return

        texto, url = resposta
        tab.editor.insert_markdown_link(texto, url)
        tab.editor.setFocus()

    def _clipboard_url(self) -> str:
        """Sugere o endereço que estiver no clipboard, se parecer um.

        Colar um link é o caso mais comum, e evitar um Ctrl+V a mais é o tipo de
        detalhe que faz o diálogo valer a pena.
        """
        from PyQt6.QtWidgets import QApplication

        texto = QApplication.clipboard().text().strip()
        if not texto or "\n" in texto:
            return ""
        if texto.startswith(("http://", "https://", "mailto:", "www.")):
            return texto
        return ""

    def insert_image(self) -> None:
        """Escolhe uma imagem do disco e a insere no documento."""
        tab = self.current_tab
        if tab is None:
            return

        origem = QFileDialog.getOpenFileName(
            self,
            "Escolher imagem",
            str(tab.path.parent if tab.path else self.config.last_directory),
            IMAGE_FILE_FILTER,
        )[0]
        if not origem:
            return

        caminho = Path(origem)
        # Só oferece copiar quando a imagem está fora da pasta do documento: se
        # já está dentro, o caminho relativo funciona e copiar duplicaria o
        # arquivo sem motivo.
        pasta = tab.path.parent if tab.path else None
        precisa_copiar = pasta is not None and not is_inside(caminho, pasta)

        resposta = ImageDialog.ask(
            self,
            alt=caminho.stem,
            can_copy=precisa_copiar,
            source=str(caminho),
        )
        if resposta is None:
            return

        alt, copiar = resposta

        try:
            preparada = prepare_image(
                caminho, tab.path, copy_external=copiar
            )
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Não foi possível inserir a imagem",
                f"{caminho}\n\n{exc}",
            )
            return

        tab.editor.insert_image(alt or preparada.alt, preparada.url)
        tab.editor.setFocus()

        if preparada.was_copied:
            self._status_message.setText(f"Imagem copiada para {preparada.copied_to}")
        elif not preparada.relative:
            self._status_message.setText(
                "Documento ainda não salvo: a imagem ficou com caminho absoluto."
            )

    def insert_emoji(self) -> None:
        """Abre o seletor de emoji ancorado no botão da barra."""
        tab = self.current_tab
        if tab is None:
            return

        if self._emoji_picker is None:
            self._emoji_picker = EmojiPicker(self)
            self._emoji_picker.emojiChosen.connect(self._on_emoji_chosen)

        # Ancora no botão da barra quando ele existe, para o popup nascer
        # apontando para o lugar de onde o usuário clicou.
        ancora = self.toolbar.widgetForAction(self.action_emoji) or self
        self._emoji_picker.open_at(ancora)

    def _on_emoji_chosen(self, char: str) -> None:
        tab = self.current_tab
        if tab is None:
            return
        if self._emoji_picker is not None:
            self._emoji_picker.hide()

        tab.editor.insert_emoji(char)
        tab.editor.setFocus()

    def _insert_text(self, text: str) -> None:
        tab = self.current_tab
        if tab is not None:
            tab.editor.insertPlainText(text)

    def _insert_code_block(self) -> None:
        tab = self.current_tab
        if tab is None:
            return
        cursor = tab.editor.textCursor()
        selected = cursor.selectedText()
        cursor.insertText(f"```python\n{selected}\n```\n")
        tab.editor.setTextCursor(cursor)

    def _insert_table(self) -> None:
        tab = self.current_tab
        if tab is None:
            return
        tab.editor.insertPlainText(
            "\n| Coluna | Coluna |\n|--------|--------|\n| valor  | valor  |\n\n"
        )

    # ==================================================================
    # Exibição
    # ==================================================================
    def _initial_theme(self) -> str:
        """Tema inicial: segue o Windows quando configurado para isso."""
        if self.config.theme_follows_system:
            return self._system_theme()
        return self.config.theme

    def _system_theme(self) -> str:
        """Tema claro/escuro configurado no sistema operacional.

        A detecção em si vive em ``theme.system_theme``, que sabe consultar o
        registro no Windows, o ``defaults`` no macOS e o ``gsettings`` no Linux.
        """
        return system_theme()
    @property
    def _theme(self) -> str:
        return getattr(self, "_current_theme", "dark")

    def set_theme(self, theme: str) -> None:
        self._apply_theme(theme, persist=True)

    def _apply_theme(self, theme: str, *, persist: bool) -> None:
        theme = theme if theme in ("light", "dark") else "dark"
        self._current_theme = theme

        if persist:
            self.config.theme = theme
            self.config.theme_follows_system = False

        # 1. Toda a interface do Qt: menus, barra de ferramentas, abas, barra
        #    lateral, barra de status, diálogos e a faixa de modo.
        apply_app_theme(QApplication.instance(), theme)

        # 2. Os ícones têm a cor gravada no pixmap, então o cache do tema
        #    anterior precisa cair antes de reaplicá-los às ações.
        clear_action_cache()
        self._refresh_action_icons(theme)

        # 3. Os widgets que guardam folha de estilo própria. O editor pinta o
        #    texto por conta (é um QPlainTextEdit com realce), e a barra lateral
        #    tem cores derivadas da paleta do Qt.
        for tab in self._tabs():
            tab.editor.apply_theme(theme)

        # 4. O preview, que é HTML e tem sua própria folha.
        self.preview.apply_theme(theme)

        (self.action_theme_light if theme == "light" else self.action_theme_dark).setChecked(True)

        if self.current_tab is None:
            self._show_empty_state()
        else:
            # A troca de tema no preview é feita por JS, sem recarregar a
            # página, então não é preciso re-renderizar aqui.
            self.preview.refresh()

    def _refresh_action_icons(self, theme: str) -> None:
        """Redesenha os ícones das ações na cor do tema.

        O registro é explícito (:attr:`_icon_actions`) em vez de uma varredura
        pelas ações: ``QAction.setData`` já está ocupado pelo modo de exibição
        nas ações do grupo Exibir, e o ícone tem a cor gravada no pixmap — então
        precisa ser recriado a cada troca de tema.
        """
        color = theme_colors(theme).icon_color()
        for action, name in self._icon_actions.items():
            action.setIcon(action_icon(name, color))

    def toggle_theme(self) -> None:
        self.set_theme("light" if self._theme == "dark" else "dark")

    def set_view_mode(self, mode: str) -> None:
        if mode not in VIEW_MODE_LABELS:
            mode = DEFAULT_VIEW_MODE
        self._view_mode = mode
        self._apply_view_mode(mode)

    def enter_edit_mode(self) -> None:
        """Sai da leitura e abre o editor.

        Entra em modo lado a lado, e não só editor: quem clicou em "Editar"
        quer ver o resultado do que escreve. Se já se estava editando, mantém
        o modo atual, para o duplo clique não tirar o preview de quem escolheu
        "somente editor".
        """
        if self._view_mode == "preview":
            self.set_view_mode("split")

        tab = self.current_tab
        if tab is not None:
            tab.editor.setFocus()

    def enter_read_mode(self) -> None:
        """Volta para a leitura."""
        self.set_view_mode("preview")

    def _apply_view_mode(self, mode: str) -> None:
        show_editor = mode in ("split", "editor")
        show_preview = mode in ("split", "preview")

        self.tabs.setVisible(show_editor)
        # A faixa acompanha o preview, mas fica visível no modo lado a lado
        # também: é por ela que se volta a ler sem passar pelo menu.
        self.mode_bar.setVisible(show_preview)
        self.preview.setVisible(show_preview)
        self.mode_bar.set_mode(mode)

        # Busca é recurso de edição: esconder o editor com a barra aberta
        # deixaria um campo de texto ativo operando sobre algo invisível.
        if not show_editor:
            self._close_search_on_all_tabs()

        action = {
            "preview": self.action_view_preview,
            "split": self.action_view_split,
            "editor": self.action_view_editor,
        }.get(mode)
        if action is not None:
            action.setChecked(True)

        if mode == "split":
            self._ensure_split_visible()

        self._enforce_mode_layout()

        if show_preview and self.current_tab is not None:
            self._schedule_render()
        if show_editor and self.current_tab is not None:
            self.current_tab.editor.setFocus()

        # O modo decide o que está habilitado — localizar e substituir só valem
        # com o editor à vista. Sem esta chamada, entrar em edição pelo botão
        # "Editar" deixaria as ações de busca cinzas, porque nada mais avisa a
        # interface de que o modo mudou.
        self._update_actions()

    def _enforce_mode_layout(self) -> None:
        """Ajusta as larguras do divisor para o modo atual.

        Precisa rodar **depois** de qualquer ``restoreState``. O estado salvo do
        divisor é independente do modo: um estado gravado em "editor e preview"
        traz largura para os dois lados, e restaurá-lo em modo de leitura
        reabriria o painel do editor — que está oculto, mas ocuparia a tela como
        uma faixa vazia no meio da janela.
        """
        sizes = self.content_splitter.sizes()
        total = sum(sizes)
        if total <= 0:
            total = max(1, self.content_splitter.width())

        if self._view_mode == "preview":
            self.content_splitter.setSizes([0, total])
        elif self._view_mode == "editor":
            self.content_splitter.setSizes([total, 0])
        elif not self._split_balanced():
            self._distribute_split()

    def _ensure_split_visible(self) -> None:
        """Redistribui o splitter quando um dos lados ficou zerado.

        O ``QSplitter`` memoriza a largura que cada filho tinha quando foi
        ocultado — zero, no caso de "somente editor" ou "somente preview". Ao
        reexibir, ele devolve zero, e o painel fica invisível mesmo com
        ``isVisible()`` verdadeiro: o usuário vê metade da janela vazia. O
        mesmo acontece ao restaurar um estado salvo nessa situação.
        """
        if self._split_balanced():
            return
        self._distribute_split()

    def _split_balanced(self) -> bool:
        sizes = self.content_splitter.sizes()
        if len(sizes) != 2:
            return True
        return sizes[0] > 0 and sizes[1] > 0

    def _distribute_split(self) -> None:
        """Divide o espaço do conteúdo ao meio."""
        sizes = self.content_splitter.sizes()
        total = sum(sizes)
        if total <= 0:
            total = max(1, self.content_splitter.width())
        half = total // 2
        self.content_splitter.setSizes([half, total - half])
        log.debug("Splitter redistribuído para %s", self.content_splitter.sizes())

    def showEvent(self, event) -> None:  # noqa: N802 - assinatura do Qt
        """Divide o espaço na primeira exibição, quando não há estado salvo.

        Antes da janela aparecer, o ``QSplitter`` não tem largura real e
        ``setSizes`` é interpretado como proporção; na prática o painel do
        preview ficava com a largura mínima, e não com metade. Só fazemos isso
        quando o usuário ainda não ajustou o divisor por conta própria.
        """
        super().showEvent(event)
        if getattr(self, "_first_show_done", False):
            return
        self._first_show_done = True

        if self._view_mode == "split" and self.config.splitter_state is None:
            QTimer.singleShot(0, self._distribute_split)

    def toggle_sidebar(self) -> None:
        visible = not self.sidebar.isVisible()
        self.sidebar.setVisible(visible)
        self.action_sidebar.setChecked(visible)
        self.config.sidebar_visible = visible

    def toggle_line_numbers(self) -> None:
        enabled = self.action_line_numbers.isChecked()
        self.config.show_line_numbers = enabled
        for tab in self._tabs():
            tab.editor.set_line_numbers_visible(enabled)

    def toggle_word_wrap(self) -> None:
        enabled = self.action_word_wrap.isChecked()
        self.config.word_wrap = enabled
        for tab in self._tabs():
            tab.editor.set_word_wrap(enabled)

    def toggle_scroll_sync(self) -> None:
        self.config.scroll_sync = self.action_scroll_sync.isChecked()

    def _zoom(self, delta: int) -> None:
        size = max(8, min(32, self.config.editor_font_size + delta))
        self.config.editor_font_size = size
        for tab in self._tabs():
            tab.editor.set_font_size(size)
        self._status_message.setText(f"Fonte do editor: {size} pt")

    # ==================================================================
    # Status / ações
    # ==================================================================
    def _update_window_title(self) -> None:
        tab = self.current_tab
        if tab is None:
            self.setWindowTitle(APP_NAME)
            self.mode_bar.set_document_name("Nenhum arquivo aberto")
            return
        prefix = "• " if tab.is_dirty else ""
        self.setWindowTitle(f"{prefix}{tab.display_name.rstrip(' •')} — {APP_NAME}")
        self.mode_bar.set_document_name(tab.absolute_title, dirty=tab.is_dirty)

    def _update_status(self) -> None:
        tab = self.current_tab
        if tab is None:
            return
        stats = tab.statistics()
        self._status_counts.setText(
            f"{stats['words']} palavras · {stats['lines']} linhas"
        )
        encoding = tab.encoding.replace("utf-8-sig", "UTF-8 BOM").replace("utf-8", "UTF-8").replace("cp1252", "Windows-1252")
        eol = "CRLF" if tab.eol == "\r\n" else "LF"
        self._status_encoding.setText(f"{encoding} · {eol}")
        self._update_position()

    def _update_position(self) -> None:
        tab = self.current_tab
        if tab is None:
            return
        cursor = tab.editor.textCursor()
        self._status_position.setText(
            f"Ln {cursor.blockNumber() + 1}, Col {cursor.positionInBlock() + 1}"
        )

    def _update_actions(self) -> None:
        tab = self.current_tab
        has_tab = tab is not None
        self.action_save.setEnabled(has_tab)
        self.action_save_as.setEnabled(has_tab)
        self.action_export_html.setEnabled(has_tab)
        self.action_export_pdf.setEnabled(has_tab)
        self.action_close_tab.setEnabled(has_tab)
        self.action_close_all.setEnabled(self.tabs.count() > 0)

        for action in (
            self.action_undo, self.action_redo, self.action_cut, self.action_copy,
            self.action_paste, self.action_select_all, self.action_bold,
            self.action_italic, self.action_strike, self.action_code,
            self.action_link, self.action_image, self.action_emoji,
            self.action_h1, self.action_h2, self.action_h3,
            self.action_bullet, self.action_numbered, self.action_task,
            self.action_quote, self.action_code_block, self.action_table,
            self.action_hr,
        ):
            action.setEnabled(has_tab)

        # Busca exige duas coisas: uma aba aberta e o editor à vista. No modo
        # de leitura não há o que procurar, então a ação fica desabilitada em
        # vez de abrir uma barra que não pode operar sobre nada.
        pode_buscar = has_tab and self._editing_available()
        for action in (
            self.action_find, self.action_find_next,
            self.action_find_previous, self.action_replace,
        ):
            action.setEnabled(pode_buscar)

        if tab is not None:
            self.action_undo.setEnabled(tab.editor.document().isUndoAvailable())
            self.action_redo.setEnabled(tab.editor.document().isRedoAvailable())

    def _rebuild_recent_menu(self) -> None:
        self._recent_menu.clear()
        files = self.config.recent_files
        if not files:
            empty = self._recent_menu.addAction("(vazio)")
            empty.setEnabled(False)
            return

        for path in files:
            action = self._recent_menu.addAction(path)
            action.triggered.connect(lambda _c=False, p=path: self.open_path(p))

        self._recent_menu.addSeparator()
        clear = self._recent_menu.addAction("Limpar lista")
        clear.triggered.connect(self._clear_recent)

    def _clear_recent(self) -> None:
        self.config.clear_recent_files()
        self._rebuild_recent_menu()
        self.tray.update_recent([])

    # ==================================================================
    # Associação de arquivos
    # ==================================================================
    def register_association(self) -> None:
        from edgemd.paths import launcher_command

        launcher = launcher_command()
        plataforma = association.platform_label()

        if is_frozen():
            detail = f"Aplicativo:\n{launcher[0]}"
        else:
            detail = (
                "Rodando do código-fonte:\n"
                + "\n".join(launcher)
                + "\n\nO clique duplo vai abrir o app por este caminho. Se você "
                "mover a pasta do projeto, rode esta opção de novo."
            )

        # O texto de cada plataforma é bem diferente — registro no Windows,
        # arquivo .desktop no Linux, bundle no macOS —, e o usuário costuma
        # achar que "não funcionou" quando na verdade o sistema funciona de
        # outro jeito. Por isso o diálogo mostra o texto do sistema atual.
        answer = QMessageBox.question(
            self,
            f"Associar arquivos .md no {plataforma}",
            f"Isto associa {association.extension_list()} ao EdgeMD.\n\n"
            f"{association.instructions()}\n\n{detail}\n\nContinuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        # No macOS quem decide se pode haver padrão é o bundle; perguntar não
        # faz sentido lá.
        make_default = True
        if plataforma != "macOS":
            make_default = (
                QMessageBox.question(
                    self,
                    "Programa padrão",
                    "Tornar o EdgeMD o programa padrão ao dar clique duplo "
                    "num .md?\n\n"
                    "Escolher “Não” adiciona o app em “Abrir com”, sem mexer na "
                    "associação que você já usa.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                == QMessageBox.StandardButton.Yes
            )

        try:
            association.register(launcher, make_default=make_default)
        except association.AssociationError as exc:
            QMessageBox.critical(self, "Falha ao associar", str(exc))
            return
        except OSError as exc:
            QMessageBox.critical(
                self, "Falha ao associar",
                f"Não foi possível gravar no registro:\n\n{exc}",
            )
            return

        if make_default:
            message = (
                "Pronto. O clique duplo em arquivos .md agora abre o EdgeMD."
            )
        else:
            message = (
                "Pronto. O app foi adicionado a “Abrir com”.\n\n"
                "Para torná-lo padrão, use botão direito no arquivo → "
                "Abrir com → Escolher outro aplicativo."
            )
        QMessageBox.information(self, "Associação concluída", message)

    def unregister_association(self) -> None:

        answer = QMessageBox.question(
            self,
            "Desfazer associação",
            "Remover o registro do EdgeMD para arquivos .md?\n\n"
            f"Se o app for o padrão, o {association.platform_label()} volta a perguntar com o que abrir.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            association.unregister()
        except (association.AssociationError, OSError) as exc:
            QMessageBox.critical(self, "Falha ao desfazer", str(exc))
            return
        QMessageBox.information(self, "Pronto", "Associações removidas.")

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            f"Sobre o {APP_NAME}",
            f"<h3>{APP_NAME} {__version__}</h3>"
            f"<p>Leitor e editor de Markdown para {association.platform_label()}.</p>"
            "<p>Renderização via Chromium (Qt WebEngine), Markdown com "
            "markdown-it-py, realce com Pygments.<br>"
            "Diagramas com Mermaid e fórmulas com KaTeX, ambos locais — "
            "funciona offline.</p>"
            "<p style='color:#888'>Atalhos: Ctrl+N novo · Ctrl+O abrir · "
            "Ctrl+S salvar · Ctrl+T tema · Ctrl+Shift+P modos de exibição</p>",
        )

    # ==================================================================
    # Bandeja / sessão / eventos
    # ==================================================================
    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_new_file(self) -> None:
        self.show_from_tray()
        self.new_file()

    def quit_application(self) -> None:
        """Fecha de verdade, ignorando o "fechar para a bandeja"."""
        if not self._confirm_close_all():
            self.show_from_tray()
            return
        self._force_close = True
        self._save_session()
        self.tray.hide()
        QApplication.instance().quit()

    def _confirm_close_all(self) -> bool:
        dirty = [tab for tab in self._tabs() if tab.is_dirty]
        if not dirty:
            return True
        return self.close_all_tabs()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - assinatura do Qt
        """Fecha para a bandeja em vez de encerrar, quando configurado assim."""
        if self._force_close:
            self._save_session()
            self.tray.hide()
            event.accept()
            return

        if self.config.close_to_tray and self.tray.is_available():
            event.ignore()
            self.hide()
            if not self.config.tray_notice_shown:
                self.config.tray_notice_shown = True
                self.tray.notify(
                    APP_NAME,
                    "O app continua rodando aqui. Clique no ícone para voltar, "
                    "ou use Sair no menu para encerrar.",
                )
            return

        if not self._confirm_close_all():
            event.ignore()
            return

        self._save_session()
        self.tray.hide()
        event.accept()

    # -- arrastar e soltar ------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802 - assinatura do Qt
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - assinatura do Qt
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if not paths:
            return

        files = [p for p in paths if Path(p).is_file()]
        folders = [p for p in paths if Path(p).is_dir()]

        if files:
            self.open_paths(files)
        # Soltar uma pasta abre a árvore nela — atalho natural para quem
        # arrasta o diretório de notas inteiro.
        if folders:
            self.sidebar.set_root(folders[0])
            self.sidebar.setVisible(True)
            self.action_sidebar.setChecked(True)
            self.config.sidebar_visible = True
        event.acceptProposedAction()

    # -- alteração externa ------------------------------------------------
    def _start_external_watch(self) -> None:
        """Verifica periodicamente se algum arquivo aberto mudou no disco."""
        self._external_check_timer = QTimer(self)
        self._external_check_timer.setInterval(4000)
        self._external_check_timer.timeout.connect(self._check_external_changes)
        self._external_check_timer.start()

    def _check_external_changes(self) -> None:
        if not self.isVisible():
            return
        for tab in self._tabs():
            # Só reclama se o app não tem alterações pendentes: se ele tem, o
            # conflito é real e vale avisar mesmo assim.
            tab.check_external_change()

    def _on_external_change(self, tab: EditorTab) -> None:
        if tab.external_prompt_open:
            return
        tab.external_prompt_open = True
        try:
            answer = QMessageBox.question(
                self,
                "Arquivo alterado",
                f"“{tab.path.name}” foi modificado por outro programa.\n\n"
                + (
                    "Você tem alterações não salvas aqui — recarregar vai "
                    "descartá-las.\n\n"
                    if tab.is_dirty
                    else ""
                )
                + "Recarregar do disco?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if answer == QMessageBox.StandardButton.Yes:
                tab.reload()
                if self.tabs.currentWidget() is tab:
                    self._schedule_render(keep_line=1)
                self._update_status()
            else:
                # O usuário escolheu manter o conteúdo atual: realinha a
                # assinatura de disco para não perguntar de novo a cada 4 s.
                tab.record_disk_signature()
        finally:
            tab.external_prompt_open = False

    # -- janela ------------------------------------------------------------
    def _restore_window_state(self) -> None:
        geometry = self.config.geometry
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1180, 760)

        state = self.config.window_state
        if state is not None:
            self.restoreState(state)

        splitter = self.config.splitter_state
        if splitter is not None:
            self.content_splitter.restoreState(splitter)

        sidebar_splitter = self.config.sidebar_splitter_state
        if sidebar_splitter is not None:
            self.main_splitter.restoreState(sidebar_splitter)

        # Um estado salvo enquanto o preview estava oculto traz largura zero
        # para ele; e um estado salvo em outro modo traz largura para um painel
        # que agora está escondido. Em ambos os casos o layout é reimposto para
        # o modo atual.
        self._enforce_mode_layout()

    def _save_window_state(self) -> None:
        self.config.geometry = self.saveGeometry()
        self.config.window_state = self.saveState()
        self.config.splitter_state = self.content_splitter.saveState()
        self.config.sidebar_splitter_state = self.main_splitter.saveState()

    def _save_session(self) -> None:
        self._save_window_state()
        files = [str(tab.path) for tab in self._tabs() if tab.path is not None]
        self.config.session_files = files
        self.config.sync()

    def restore_session(self) -> None:
        """Reabre os arquivos da sessão anterior, se configurado."""
        if not self.config.restore_session:
            return
        files = self.config.session_files
        if files:
            self.open_paths(files)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - assinatura do Qt
        """Acompanha a troca de tema do sistema, quando configurado assim."""
        if (
            event.type() in _THEME_CHANGE_EVENTS
            and self.config.theme_follows_system
        ):
            self._apply_theme(self._system_theme(), persist=False)
        super().changeEvent(event)
