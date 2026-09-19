"""Preferências do usuário, persistidas no registro do Windows via QSettings.

QSettings grava em ``HKCU\\Software\\EdgeMD\\EdgeMD``. Usamos ele em vez de
um JSON próprio porque já resolve o caso chato de escrita concorrente e de
onde guardar as coisas no Windows.

Todos os acessos passam por propriedades tipadas: ler do QSettings devolve
sempre string (ou None), e comparar ``"true"`` com True é fonte clássica de
bug silencioso.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

from PyQt6.QtCore import QByteArray, QSettings

from edgemd import APP_ID, ORG_NAME

log = logging.getLogger(__name__)

MAX_RECENT_FILES = 12

#: Modos de exibição. O padrão é leitura: o app é um leitor de Markdown, e a
#: edição é a exceção — entra por um clique, e não pelo estado da última sessão.
#: Guardar o modo entre execuções faria um .md aberto no dia seguinte começar
#: em modo de edição, contrariando esse padrão.
VIEW_MODES = ("preview", "split", "editor")

#: Modo com que o app abre. Fica aqui, e não em ``window``, para poder ser
#: verificado sem importar a janela — que sobe o Chromium só para existir.
DEFAULT_VIEW_MODE = "preview"

#: Modos em que o editor está à vista.
EDITING_VIEW_MODES = ("split", "editor")

THEMES = ("light", "dark")


def editing_available(view_mode: str) -> bool:
    """True quando o modo atual mostra o editor.

    Decisões que dependem de "dá para editar agora?" — habilitar localizar e
    substituir, por exemplo — passam por aqui. É regra de produto, não detalhe
    de widget, então mora junto das preferências: assim dá para verificá-la sem
    abrir janela nenhuma.
    """
    return view_mode in EDITING_VIEW_MODES


def _as_bool(value: Any, default: bool) -> bool:
    """Converte o que o QSettings devolve em bool de verdade.

    O QSettings no Windows pode devolver ``True``, ``"true"``, ``"1"`` ou
    ``1`` dependendo de como o valor foi gravado.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "sim"}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class AppConfig:
    """Acesso tipado às preferências.

    ``settings_path`` existe para os testes: apontando para um arquivo
    temporário, a suíte não toca no registro real e não apaga as preferências
    de quem está desenvolvendo. Em produção fica ``None`` e o QSettings usa o
    registro do Windows.
    """

    def __init__(self, settings_path: str | Path | None = None) -> None:
        if settings_path is None:
            self._settings = QSettings(ORG_NAME, APP_ID)
        else:
            path = Path(settings_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._settings = QSettings(str(path), QSettings.Format.IniFormat)

    # -- genéricos --------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self._settings.value(key, default)

    def set(self, key: str, value: Any) -> None:
        self._settings.setValue(key, value)

    def sync(self) -> None:
        self._settings.sync()

    # -- tema -------------------------------------------------------------
    @property
    def theme(self) -> str:
        value = str(self._settings.value("appearance/theme", "dark"))
        return value if value in THEMES else "dark"

    @theme.setter
    def theme(self, value: str) -> None:
        self._settings.setValue("appearance/theme", value if value in THEMES else "dark")

    @property
    def theme_follows_system(self) -> bool:
        return _as_bool(self._settings.value("appearance/follow_system"), True)

    @theme_follows_system.setter
    def theme_follows_system(self, value: bool) -> None:
        self._settings.setValue("appearance/follow_system", bool(value))

    # -- visualização -----------------------------------------------------
    @property
    def sidebar_visible(self) -> bool:
        return _as_bool(self._settings.value("view/sidebar_visible"), True)

    @sidebar_visible.setter
    def sidebar_visible(self, value: bool) -> None:
        self._settings.setValue("view/sidebar_visible", bool(value))

    @property
    def scroll_sync(self) -> bool:
        return _as_bool(self._settings.value("view/scroll_sync"), True)

    @scroll_sync.setter
    def scroll_sync(self, value: bool) -> None:
        self._settings.setValue("view/scroll_sync", bool(value))

    @property
    def content_font_size(self) -> int:
        return max(10, min(32, _as_int(self._settings.value("view/content_font_size"), 16)))

    @content_font_size.setter
    def content_font_size(self, value: int) -> None:
        self._settings.setValue("view/content_font_size", max(10, min(32, int(value))))

    @property
    def content_width(self) -> int:
        return max(30, min(120, _as_int(self._settings.value("view/content_width"), 54)))

    @content_width.setter
    def content_width(self, value: int) -> None:
        self._settings.setValue("view/content_width", max(30, min(120, int(value))))

    # -- editor -----------------------------------------------------------
    @property
    def editor_font_size(self) -> int:
        return max(8, min(32, _as_int(self._settings.value("editor/font_size"), 14)))

    @editor_font_size.setter
    def editor_font_size(self, value: int) -> None:
        self._settings.setValue("editor/font_size", max(8, min(32, int(value))))

    @property
    def word_wrap(self) -> bool:
        return _as_bool(self._settings.value("editor/word_wrap"), True)

    @word_wrap.setter
    def word_wrap(self, value: bool) -> None:
        self._settings.setValue("editor/word_wrap", bool(value))

    @property
    def toolbar_show_text(self) -> bool:
        """Se a barra de ferramentas mostra o nome sob cada ícone.

        O padrão é só ícone, como nas barras do Office: com 30 ações, o texto
        embaixo deixaria a barra larga a ponto de empurrar os grupos para fora
        da tela em janelas estreitas.
        """
        return _as_bool(self._settings.value("view/toolbar_show_text"), False)

    @toolbar_show_text.setter
    def toolbar_show_text(self, value: bool) -> None:
        self._settings.setValue("view/toolbar_show_text", bool(value))

    @property
    def show_line_numbers(self) -> bool:
        return _as_bool(self._settings.value("editor/line_numbers"), True)

    @show_line_numbers.setter
    def show_line_numbers(self, value: bool) -> None:
        self._settings.setValue("editor/line_numbers", bool(value))

    @property
    def tab_width(self) -> int:
        return max(2, min(8, _as_int(self._settings.value("editor/tab_width"), 4)))

    @tab_width.setter
    def tab_width(self, value: int) -> None:
        self._settings.setValue("editor/tab_width", max(2, min(8, int(value))))

    @property
    def autosave(self) -> bool:
        return _as_bool(self._settings.value("editor/autosave"), False)

    @autosave.setter
    def autosave(self, value: bool) -> None:
        self._settings.setValue("editor/autosave", bool(value))

    # -- renderização -----------------------------------------------------
    @property
    def show_mermaid(self) -> bool:
        return _as_bool(self._settings.value("render/mermaid"), True)

    @show_mermaid.setter
    def show_mermaid(self, value: bool) -> None:
        self._settings.setValue("render/mermaid", bool(value))

    @property
    def show_math(self) -> bool:
        return _as_bool(self._settings.value("render/math"), True)

    @show_math.setter
    def show_math(self, value: bool) -> None:
        self._settings.setValue("render/math", bool(value))

    @property
    def render_delay_ms(self) -> int:
        return max(60, min(2000, _as_int(self._settings.value("render/delay_ms"), 220)))

    @render_delay_ms.setter
    def render_delay_ms(self, value: int) -> None:
        self._settings.setValue("render/delay_ms", max(60, min(2000, int(value))))

    # -- janela -----------------------------------------------------------
    @property
    def geometry(self) -> QByteArray | None:
        value = self._settings.value("window/geometry")
        return value if isinstance(value, QByteArray) and not value.isEmpty() else None

    @geometry.setter
    def geometry(self, value: QByteArray) -> None:
        self._settings.setValue("window/geometry", value)

    @property
    def window_state(self) -> QByteArray | None:
        value = self._settings.value("window/state")
        return value if isinstance(value, QByteArray) and not value.isEmpty() else None

    @window_state.setter
    def window_state(self, value: QByteArray) -> None:
        self._settings.setValue("window/state", value)

    @property
    def splitter_state(self) -> QByteArray | None:
        value = self._settings.value("window/splitter")
        return value if isinstance(value, QByteArray) and not value.isEmpty() else None

    @splitter_state.setter
    def splitter_state(self, value: QByteArray) -> None:
        self._settings.setValue("window/splitter", value)

    @property
    def sidebar_splitter_state(self) -> QByteArray | None:
        value = self._settings.value("window/sidebar_splitter")
        return value if isinstance(value, QByteArray) and not value.isEmpty() else None

    @sidebar_splitter_state.setter
    def sidebar_splitter_state(self, value: QByteArray) -> None:
        self._settings.setValue("window/sidebar_splitter", value)

    # -- bandeja ----------------------------------------------------------
    @property
    def close_to_tray(self) -> bool:
        return _as_bool(self._settings.value("tray/close_to_tray"), True)

    @close_to_tray.setter
    def close_to_tray(self, value: bool) -> None:
        self._settings.setValue("tray/close_to_tray", bool(value))

    @property
    def start_minimized(self) -> bool:
        return _as_bool(self._settings.value("tray/start_minimized"), False)

    @start_minimized.setter
    def start_minimized(self, value: bool) -> None:
        self._settings.setValue("tray/start_minimized", bool(value))

    @property
    def tray_notice_shown(self) -> bool:
        return _as_bool(self._settings.value("tray/notice_shown"), False)

    @tray_notice_shown.setter
    def tray_notice_shown(self, value: bool) -> None:
        self._settings.setValue("tray/notice_shown", bool(value))

    # -- arquivos recentes ------------------------------------------------
    @property
    def recent_files(self) -> list[str]:
        value = self._settings.value("files/recent", [])
        if isinstance(value, str):
            # QSettings devolve string quando há só um item gravado.
            value = [value]
        if not isinstance(value, (list, tuple)):
            return []
        out: list[str] = []
        for item in value:
            text = str(item)
            # Descarta entradas de arquivos que não existem mais.
            if text and Path(text).is_file() and text not in out:
                out.append(text)
        return out[:MAX_RECENT_FILES]

    def add_recent_file(self, path: str | Path) -> None:
        resolved = str(Path(path).resolve())
        items = [p for p in self.recent_files if p != resolved]
        items.insert(0, resolved)
        self._settings.setValue("files/recent", items[:MAX_RECENT_FILES])

    def remove_recent_file(self, path: str | Path) -> None:
        resolved = str(Path(path).resolve())
        self._settings.setValue(
            "files/recent", [p for p in self.recent_files if p != resolved]
        )

    def clear_recent_files(self) -> None:
        self._settings.setValue("files/recent", [])

    # -- último diretório -------------------------------------------------
    @property
    def last_directory(self) -> Path:
        """Última pasta usada, com uma cadeia de fallback que sempre existe.

        Não basta cair para ``~/Documents``: em máquinas com OneDrive a pasta
        local costuma não existir (o perfil é redirecionado), e devolver um
        caminho inválido faz o diálogo de arquivo abrir num lugar vazio.
        Por isso cada candidato é verificado antes de ser aceito.
        """
        value = self._settings.value("files/last_dir", "")
        candidates = []
        if value:
            candidates.append(Path(str(value)))
        candidates.extend(
            [
                Path.home() / "Documents",
                Path.home() / "Documentos",
                Path.home(),
                Path.cwd(),
            ]
        )
        for candidate in candidates:
            try:
                if candidate.is_dir():
                    return candidate
            except OSError:
                continue
        # Último recurso: o diretório atual, que quase certamente existe.
        return Path.cwd()

    @last_directory.setter
    def last_directory(self, value: str | Path) -> None:
        path = Path(value)
        if path.is_dir():
            self._settings.setValue("files/last_dir", str(path))

    # -- sessão -----------------------------------------------------------
    @property
    def restore_session(self) -> bool:
        return _as_bool(self._settings.value("session/restore"), True)

    @restore_session.setter
    def restore_session(self, value: bool) -> None:
        self._settings.setValue("session/restore", bool(value))

    @property
    def session_files(self) -> list[str]:
        value = self._settings.value("session/files", [])
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, (list, tuple)):
            return []
        return [str(p) for p in value if str(p) and Path(str(p)).is_file()]

    @session_files.setter
    def session_files(self, values: Iterable[str | Path]) -> None:
        self._settings.setValue("session/files", [str(v) for v in values])
