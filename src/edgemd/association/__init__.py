"""Associação de arquivos ``.md``, escolhendo o backend da plataforma.

A fachada existe para que o resto do app não precise saber onde está rodando:
``register()``, ``unregister()``, ``status()`` e ``instructions()`` fazem a coisa
certa em cada sistema.

O que muda entre eles é grande o bastante para justificar três implementações
separadas, e não uma cheia de condicionais:

* **Windows** grava no registro, em ``HKEY_CURRENT_USER``, em três camadas
  (ProgID, OpenWithProgids e Capabilities).
* **Linux** instala um arquivo ``.desktop`` com ``MimeType=``, os ícones do tema
  hicolor, e define o padrão por ``xdg-mime``.
* **macOS** não tem o que gravar: os tipos são declarados no ``Info.plist`` do
  bundle, e a associação nasce no empacotamento. Em tempo de execução só dá para
  conferir a declaração e, com o ``duti``, assumir o padrão.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import ModuleType

from edgemd.association import linux, macos, windows
from edgemd.association.common import (
    APP_BUNDLE_ID,
    APP_FRIENDLY_NAME,
    DESKTOP_ID,
    EXECUTABLE_NAME,
    EXTENSIONS,
    MIME_TYPES,
    AssociationError,
    AssociationStatus,
    build_command,
    extension_list,
)

log = logging.getLogger(__name__)

__all__ = [
    "APP_BUNDLE_ID",
    "APP_FRIENDLY_NAME",
    "DESKTOP_ID",
    "EXECUTABLE_NAME",
    "EXTENSIONS",
    "MIME_TYPES",
    "AssociationError",
    "AssociationStatus",
    "build_command",
    "backend",
    "extension_list",
    "instructions",
    "is_supported",
    "platform_label",
    "register",
    "status",
    "unregister",
]


def backend() -> ModuleType:
    """Módulo de associação da plataforma atual.

    O Linux é o padrão para qualquer sistema que não seja Windows nem macOS —
    os BSDs e outros Unixes usam o mesmo ``.desktop``.
    """
    if sys.platform == "win32":
        return windows
    if sys.platform == "darwin":
        return macos
    return linux


def platform_label() -> str:
    """Nome da plataforma, para mensagens ao usuário."""
    if sys.platform == "win32":
        return "Windows"
    if sys.platform == "darwin":
        return "macOS"
    if sys.platform.startswith("linux"):
        return "Linux"
    return sys.platform


def is_supported() -> bool:
    """True quando a plataforma atual permite associar arquivos.

    Pergunta ao backend a cada chamada, em vez de ler uma constante fixada no
    import: assim a resposta acompanha a plataforma real em tempo de execução.
    """
    verificador = getattr(backend(), "is_supported", None)
    if verificador is None:  # pragma: no cover - backend incompleto
        return False
    return bool(verificador())


def status(
    launcher: list[str] | None = None, icon_file: str | Path | None = None
) -> AssociationStatus:
    """Lê o estado atual da associação."""
    try:
        return backend().status(launcher, icon_file)
    except AssociationError as exc:
        return AssociationStatus(
            supported=False, is_default=False, in_open_with=False, detail=str(exc)
        )


def register(
    launcher: list[str],
    icon_file: str | Path | None = None,
    *,
    make_default: bool = True,
) -> AssociationStatus:
    """Associa os arquivos ``.md`` a este programa.

    Levanta :class:`AssociationError` quando a plataforma não permite, ou quando
    a gravação falha — o chamador mostra a mensagem, que já vem explicando o
    motivo específico do sistema.
    """
    return backend().register(launcher, icon_file, make_default=make_default)


def unregister() -> None:
    """Desfaz a associação."""
    backend().unregister()


def instructions() -> str:
    """Texto que explica, nesta plataforma, como a associação funciona.

    Existe porque as três respostas são bem diferentes, e o usuário costuma
    achar que "não funcionou" quando na verdade o sistema funciona de outro
    jeito.
    """
    return backend().instructions()
