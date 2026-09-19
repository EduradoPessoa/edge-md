"""Ponto de entrada: inicializa o Qt, a instância única e a janela principal.

A ordem de inicialização aqui não é arbitrária:

1. **``QtWebEngineWidgets`` antes de ``QApplication``.** O Chromium precisa que
   ``AA_ShareOpenGLContexts`` esteja definido antes de o objeto de aplicação
   existir; importar o módulo faz isso. Inverter a ordem derruba o app no
   primeiro preview com "WebEngineContext used before QtWebEngine initialized".
2. **Instância única antes da janela.** Se já existe uma instância viva, este
   processo só entrega os caminhos dos arquivos e sai — sem criar janela.
3. **``setQuitOnLastWindowClosed(False)``** para que esconder a janela na
   bandeja não encerre o processo.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Este import PRECISA vir antes do QApplication (ver docstring do módulo).
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (efeito colateral necessário)

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from edgemd import APP_ID, APP_NAME, ORG_NAME, __version__
from edgemd.config import AppConfig
from edgemd.icons import app_icon
from edgemd.render import MarkdownRenderer
from edgemd.safety import install_exception_hook
from edgemd.single_instance import SingleInstance
from edgemd.theme import apply_app_theme, system_theme

log = logging.getLogger(__name__)

#: Nome do canal de IPC. Fixo para que todas as execuções se encontrem.
IPC_KEY = "edgemd-single-instance-v1"


def initial_theme(config: AppConfig) -> str:
    """Tema com que o app abre.

    Segue o sistema quando a preferência é essa (padrão), senão usa o que o
    usuário escolheu por último. A detecção por plataforma vive em
    ``theme.system_theme``.
    """
    if not config.theme_follows_system:
        return config.theme
    return system_theme()

# --------------------------------------------------------------------------
# Argumentos
# --------------------------------------------------------------------------

def parse_arguments(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    """Separa as opções do app dos caminhos de arquivo.

    Usa ``parse_known_args`` porque o Windows às vezes injeta argumentos
    próprios (por exemplo ``-Embedding`` em chamadas COM) que não são erro.
    """
    parser = argparse.ArgumentParser(
        prog="edgemd",
        description="Leitor e editor de arquivos Markdown.",
        add_help=True,
    )
    parser.add_argument("files", nargs="*", help="arquivos .md a abrir")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument(
        "--hidden", action="store_true",
        help="inicia direto na bandeja, sem mostrar a janela",
    )
    parser.add_argument(
        "--new", action="store_true",
        help="abre um documento novo, ignorando a sessão anterior",
    )
    parser.add_argument(
        "--no-session", action="store_true",
        help="não reabre os arquivos da sessão anterior",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="log detalhado no console",
    )

    known, unknown = parser.parse_known_args(argv)
    return known, unknown


def _clean_paths(raw: list[str]) -> list[str]:
    """Filtra os argumentos que realmente são arquivos existentes."""
    paths: list[str] = []
    for item in raw:
        if item.startswith("-"):
            continue
        try:
            if Path(item).is_file():
                paths.append(str(Path(item).resolve()))
        except OSError:
            continue
    return paths


# --------------------------------------------------------------------------
# Log
# --------------------------------------------------------------------------

def setup_logging(verbose: bool, app: QApplication | None = None) -> Path | None:
    """Loga em arquivo, e também no console quando ``--verbose``.

    Como o app roda por ``pythonw``/``.exe --windowed``, não há stderr visível:
    sem arquivo de log, uma falha em produção viraria silêncio.

    **Precisa ser chamada depois de criar o QApplication e de definir o nome do
    aplicativo.** O ``QStandardPaths`` monta o caminho a partir do nome do app;
    chamada antes disso, ele devolve algo genérico como
    ``AppData\\Local\\python``, e o log acaba fora da pasta do programa — o
    caminho que a própria mensagem de erro do app indica ao usuário.
    """
    handlers: list[logging.Handler] = []
    log_path: Path | None = None

    try:
        from PyQt6.QtCore import QStandardPaths

        base = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )
        log_dir = Path(base) if base else Path.home() / ".edgemd"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "edgemd.log"
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    except OSError:
        log_path = None

    if verbose or sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers or None,
        force=True,
    )
    return log_path


def log_file_hint() -> str:
    """Caminho do log para mostrar ao usuário em caso de falha.

    Resolvido na hora, porque o nome do aplicativo precisa já estar definido
    para o caminho bater com o arquivo que ``setup_logging`` gravou.
    """
    from PyQt6.QtCore import QStandardPaths

    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    if base:
        return str(Path(base) / "edgemd.log")
    return str(Path.home() / ".edgemd" / "edgemd.log")


# --------------------------------------------------------------------------
# Aplicativo
# --------------------------------------------------------------------------

class Application:
    """Coordena instância única, janela e mensagens vindas de outros processos."""

    def __init__(self, app: QApplication, config: AppConfig) -> None:
        self.app = app
        self.config = config
        self.renderer = MarkdownRenderer()
        self.window = None
        self.instance = SingleInstance(IPC_KEY)

    # ------------------------------------------------------------------
    def run(self, args: argparse.Namespace, paths: list[str]) -> int:
        is_primary = self.instance.try_become_primary()

        if not is_primary:
            # Já existe uma instância: entrega os arquivos e sai.
            delivered = self.instance.send({"action": "open", "paths": paths})
            if delivered:
                log.info("Arquivos entregues à instância existente: %s", paths)
                return 0
            # O canal estava morto (processo anterior travou). Tentamos de novo
            # como primária em vez de sair sem abrir nada.
            log.warning("Instância existente não respondeu; assumindo como primária.")
            if not self.instance.try_become_primary():
                log.error("Não foi possível assumir como instância primária.")

        self.instance.messageReceived.connect(self._on_message)
        self.app.aboutToQuit.connect(self.instance.close)

        return self._start(args, paths)

    # ------------------------------------------------------------------
    def _start(self, args: argparse.Namespace, paths: list[str]) -> int:
        from edgemd.window import MainWindow

        self.window = MainWindow(
            self.config,
            self.renderer,
            start_hidden=args.hidden or self.config.start_minimized,
        )

        # A sessão anterior só é reaberta quando nenhum arquivo foi passado na
        # linha de comando: abrir um .md pelo Explorer e ainda receber as abas
        # antigas seria surpreendente.
        if paths:
            self.window.open_paths(paths)
        elif not args.no_session and not args.new:
            self.window.restore_session()
        elif args.new:
            self.window.new_file()

        if not (args.hidden or self.config.start_minimized):
            self.window.show()

        return self.app.exec()

    # ------------------------------------------------------------------
    def _on_message(self, payload: dict) -> None:
        """Processa um pedido vindo de outro processo."""
        action = payload.get("action")
        log.debug("Mensagem recebida: %s", payload)

        if self.window is None:
            return

        if action == "open":
            raw = payload.get("paths") or []
            paths = _clean_paths([str(p) for p in raw])
            if paths:
                self.window.open_paths(paths)
            self.window.show_from_tray()

        elif action == "new":
            self.window.show_from_tray()
            self.window.new_file()

        elif action == "quit":
            self.window.quit_application()


def install_translations(app: QApplication) -> bool:
    """Carrega a tradução do Qt para o idioma do sistema.

    Sem isto, os botões dos diálogos padrão saem em inglês — "Cancel", "Yes",
    "No" — no meio de uma interface em português, porque o texto deles vem do
    próprio Qt, e não do app.

    Traduzir cada diálogo à mão resolveria só os que a gente escreveu; carregar
    o catálogo do Qt corrige todos de uma vez, inclusive os que ainda forem
    criados. O PyQt6 traz os arquivos ``.qm`` junto, então não há dependência
    extra.

    Devolve False quando não há tradução para o idioma — o app segue em inglês
    nos diálogos, que é o padrão do Qt.
    """
    from PyQt6.QtCore import QLibraryInfo, QLocale, QTranslator

    pasta = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    locale = QLocale.system()

    # O Qt nomeia os catálogos com underscore ("qtbase_pt_BR.qm"), enquanto o
    # uiLanguages() devolve com hífen ("pt-BR"). Sem converter, o load falha em
    # silêncio e os diálogos continuam em inglês — que foi o que aconteceu na
    # primeira versão desta função.
    candidatos: list[str] = []
    for nome in locale.uiLanguages():
        canonico = nome.replace("-", "_")
        candidatos.extend([f"qtbase_{canonico}", f"qt_{canonico}"])
        # A forma curta também vale: quando só existe a tradução genérica do
        # idioma, "pt_BR" precisa cair para "pt".
        curto = canonico.split("_")[0]
        candidatos.extend([f"qtbase_{curto}", f"qt_{curto}"])

    for catalogo in candidatos:
        tradutor = QTranslator(app)
        if tradutor.load(catalogo, pasta):
            # A referência precisa sobreviver: um QTranslator destruído deixa
            # de traduzir, e o objeto sairia de escopo aqui.
            instalados = getattr(app, "_tradutores", None) or []
            instalados.append(tradutor)
            app._tradutores = instalados  # type: ignore[attr-defined]
            app.installTranslator(tradutor)
            log.debug("Tradução do Qt carregada: %s", catalogo)
            return True

    log.debug("Sem tradução do Qt para %s; diálogos padrão em inglês.", locale.name())
    return False


def main(argv: list[str] | None = None) -> int:
    """Entrada do programa."""
    argv = list(sys.argv if argv is None else argv)
    args, unknown = parse_arguments(argv[1:])

    app = QApplication(argv)
    # O nome do aplicativo precisa vir antes do logging: é ele que define a
    # pasta onde o log é gravado.
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())
    # Esconder na bandeja não pode encerrar o processo.
    app.setQuitOnLastWindowClosed(False)

    # O tema veste toda a interface do Qt (menus, barras, abas, diálogos), e
    # não só o preview. Aplicado aqui para que nada apareça no visual nativo
    # antes de a janela montar a sua parte.
    config = AppConfig()
    apply_app_theme(app, initial_theme(config))

    log_path = setup_logging(args.verbose, app)
    if unknown:
        log.debug("Argumentos ignorados: %s", unknown)
    log.info("%s %s iniciando", APP_NAME, __version__)
    if log_path:
        log.debug("Log em %s", log_path)

    paths = _clean_paths(argv[1:])

    # Rede de segurança global: sem isto, uma exceção fora de um try interrompe
    # o laço de eventos e o app morre sem avisar nada — nem no console, já que
    # ele roda por pythonw.
    install_translations(app)
    install_exception_hook(app)

    application = Application(app, config)
    try:
        return application.run(args, paths)
    except Exception:  # noqa: BLE001 - última barreira antes de sumir sem traço
        log.exception("Falha fatal na inicialização.")
        # Erro visível: sem console, uma exceção não tratada desapareceria.
        hint = log_file_hint()
        QTimer.singleShot(
            0,
            lambda: QMessageBox.critical(
                None,
                f"{APP_NAME} — falha ao iniciar",
                f"O aplicativo não conseguiu iniciar.\n\nDetalhes em:\n{hint}",
            ),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
