"""Operações de integração com o sistema operacional.

Reúne o que muda entre Windows, Linux e macOS e que o resto do app não deveria
precisar saber: mandar um arquivo para a Lixeira, mostrar um arquivo no
gerenciador de pastas e abrir com o programa padrão.

Em todos os casos a regra é a mesma: **preferir o caminho que dá para desfazer**.
Apagar de vez o arquivo de alguém por causa de um clique errado num app de notas
é irrecuperável, então a Lixeira vem sempre primeiro, e a remoção direta é o
último recurso — registrada no log, para não passar em silêncio.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def platform_name() -> str:
    if sys.platform == "win32":
        return "Windows"
    if sys.platform == "darwin":
        return "macOS"
    return "Linux"


def trash_name() -> str:
    """Como a Lixeira se chama nesta plataforma."""
    return "Lixeira do Windows" if sys.platform == "win32" else "Lixeira"


# --------------------------------------------------------------------------
# Lixeira
# --------------------------------------------------------------------------

def move_to_trash(target: str | Path) -> None:
    """Manda um arquivo ou pasta para a Lixeira do sistema.

    Levanta ``OSError`` se não conseguir nem pela Lixeira nem pela remoção
    direta, para o chamador avisar o usuário em vez de falhar calado.
    """
    caminho = Path(target)
    if not caminho.exists():
        return

    if sys.platform == "win32":
        if _trash_windows(caminho):
            return
    elif sys.platform == "darwin":
        if _trash_macos(caminho):
            return
    else:
        if _trash_freedesktop(caminho):
            return

    log.warning(
        "Lixeira indisponível nesta plataforma; removendo %s definitivamente.",
        caminho,
    )
    _remove_permanently(caminho)


def _remove_permanently(caminho: Path) -> None:
    if caminho.is_dir():
        shutil.rmtree(caminho)
    else:
        caminho.unlink()


def _trash_windows(caminho: Path) -> bool:
    """Usa a API de Lixeira do .NET pelo PowerShell.

    A biblioteca padrão do Python não expõe a Lixeira, e o ``SHFileOperation``
    exigiria ``ctypes`` com estruturas que mudam de layout entre versões.
    """
    script = (
        "Add-Type -AssemblyName Microsoft.VisualBasic;"
        "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
        f"'{caminho}',"
        "'OnlyErrorDialogs','SendToRecycleBin')"
        if caminho.is_file()
        else "Add-Type -AssemblyName Microsoft.VisualBasic;"
        "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory("
        f"'{caminho}',"
        "'OnlyErrorDialogs','SendToRecycleBin')"
    )
    return _run_quiet(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    )


def _trash_freedesktop(caminho: Path) -> bool:
    """``gio trash`` é o caminho padrão do freedesktop.

    O ``trash-cli`` é o plano B: faz o mesmo, mas não vem instalado por padrão
    em todas as distribuições.
    """
    if _run_quiet(["gio", "trash", str(caminho)]):
        return True

    if shutil.which("trash-put"):
        return _run_quiet(["trash-put", str(caminho)])

    # Último recurso antes de apagar de vez: mover para a pasta da Lixeira
    # seguindo a especificação, que é o que o gerenciador de arquivos lê.
    return _trash_by_spec(caminho)


def _trash_by_spec(caminho: Path) -> bool:
    """Move para ``~/.local/share/Trash`` conforme a especificação do freedesktop."""
    base = Path(
        os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    ) / "Trash"

    try:
        arquivos = base / "files"
        info = base / "info"
        arquivos.mkdir(parents=True, exist_ok=True)
        info.mkdir(parents=True, exist_ok=True)

        destino = arquivos / caminho.name
        if destino.exists():
            import time

            destino = arquivos / f"{caminho.stem}.{int(time.time())}{caminho.suffix}"

        shutil.move(str(caminho), str(destino))

        # O arquivo .trashinfo é o que registra o caminho original, para o
        # gerenciador de arquivos poder restaurar.
        from urllib.parse import quote

        original = quote(str(caminho.resolve()), safe="/")
        (info / f"{destino.name}.trashinfo").write_text(
            "[Trash Info]\n"
            f"Path={original}\n"
            f"DeletionDate={_now_iso()}\n",
            encoding="utf-8",
        )
        return True
    except OSError as exc:
        log.debug("Não foi possível usar a Lixeira do freedesktop: %s", exc)
        return False


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _trash_macos(caminho: Path) -> bool:
    """No macOS, quem move para a Lixeira é o Finder, via AppleScript."""
    script = f'tell application "Finder" to delete POSIX file "{caminho}"'
    return _run_quiet(["osascript", "-e", script])


# --------------------------------------------------------------------------
# Abrir e mostrar
# --------------------------------------------------------------------------

def reveal_in_file_manager(target: str | Path) -> bool:
    """Mostra o arquivo no gerenciador de pastas do sistema.

    Devolve True quando conseguiu. Cada sistema destaca o arquivo de um jeito:
    o Explorer seleciona, o Finder revela, e o Linux depende do gerenciador.
    """
    caminho = Path(target)

    try:
        if sys.platform == "win32":
            if caminho.is_file():
                subprocess.Popen(["explorer", "/select,", str(caminho)])
            else:
                os.startfile(str(caminho))  # noqa: S606 - API do Windows
            return True

        if sys.platform == "darwin":
            alvo = caminho if caminho.is_dir() else caminho.parent
            subprocess.Popen(["open", "-R" if caminho.is_file() else "", str(alvo)])
            return True

        alvo = caminho if caminho.is_dir() else caminho.parent
        # `xdg-open` é o único nome garantido pela especificação; os outros
        # cobrem ambientes que não instalam ele.
        for comando in ("xdg-open", "gio", "nemo", "dolphin", "thunar"):
            if shutil.which(comando):
                if comando == "gio":
                    _run_quiet(["gio", "open", str(alvo)])
                else:
                    subprocess.Popen([comando, str(alvo)])
                return True
    except OSError as exc:
        log.error("Falha ao mostrar %s: %s", caminho, exc)

    return False


def open_with_default(target: str | Path) -> bool:
    """Abre um arquivo ou URL com o programa padrão do sistema."""
    caminho = str(target)
    try:
        if sys.platform == "win32":
            os.startfile(caminho)  # noqa: S606 - API do Windows
            return True
        if sys.platform == "darwin":
            subprocess.Popen(["open", caminho])
            return True
        subprocess.Popen(["xdg-open", caminho])
        return True
    except OSError as exc:
        log.error("Falha ao abrir %s: %s", caminho, exc)
        return False


# --------------------------------------------------------------------------

def _run_quiet(command: list[str]) -> bool:
    """Executa e devolve sucesso. Nunca levanta, nunca imprime."""
    if shutil.which(command[0]) is None:
        log.debug("%s não encontrado no PATH.", command[0])
        return False
    try:
        resultado = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("Falha ao executar %s: %s", command, exc)
        return False

    if resultado.returncode != 0:
        log.debug(
            "%s terminou com %d: %s",
            command[0], resultado.returncode, resultado.stderr.strip()[:200],
        )
        return False
    return True
