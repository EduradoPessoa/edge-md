"""Resolução de caminhos de recursos e do executável atual.

Precisa funcionar em dois cenários bem diferentes:

* rodando do código-fonte (``pythonw run.pyw``), onde os assets ficam ao lado
  dos módulos dentro de ``src/edgemd``;
* empacotado pelo PyInstaller (``--onefile``), onde os assets são extraídos
  para uma pasta temporária exposta em ``sys._MEIPASS``.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """True quando o código roda dentro de um bundle PyInstaller."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def resource_root() -> Path:
    """Raiz onde vivem os arquivos de dados empacotados.

    Em bundle onefile, ``sys._MEIPASS``; no código-fonte, o diretório do pacote.
    """
    if is_frozen():
        # O PyInstaller coloca os dados na raiz da pasta temporária.
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def asset_path(*parts: str) -> Path:
    """Caminho absoluto de um asset dentro de ``render/assets``."""
    if is_frozen():
        return resource_root().joinpath("render", "assets", *parts)
    return Path(__file__).resolve().parent.joinpath("render", "assets", *parts)


def icon_path(name: str) -> Path:
    """Caminho absoluto de um ícone em ``resources/icons``."""
    if is_frozen():
        return resource_root().joinpath("resources", "icons", name)
    return Path(__file__).resolve().parent.joinpath("resources", "icons", name)


def launcher_command() -> list[str]:
    """Comando que o Windows deve executar para abrir um arquivo .md.

    Em bundle, o próprio executável. No código-fonte, o ``pythonw.exe`` que
    está rodando agora mais o ``run.pyw``. Usamos ``pythonw`` para não abrir
    console.
    """
    if is_frozen():
        return [str(Path(sys.executable).resolve())]

    # sys.executable aponta para python.exe mesmo sob pythonw em alguns casos,
    # então derivamos o pythonw ao lado dele.
    exe = Path(sys.executable).resolve()
    pythonw = exe.with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = exe

    run_pyw = Path(__file__).resolve().parents[2] / "run.pyw"
    return [str(pythonw), str(run_pyw)]
