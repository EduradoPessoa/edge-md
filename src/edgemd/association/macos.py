"""Associação de arquivos no macOS.

No macOS não existe registro para gravar: quem declara que um aplicativo abre
Markdown é o ``Info.plist`` **dentro do bundle** (``CFBundleDocumentTypes``), e
o LaunchServices monta a lista de "Abrir com" a partir dos bundles instalados.
Ou seja, a associação nasce no empacotamento, não em tempo de execução — é por
isso que o ``edgemd.spec`` traz um ``info_plist`` completo.

O que sobra para o tempo de execução:

* dizer ao usuário se o bundle está corretamente declarado;
* tornar o app **padrão**, o que exige o LaunchServices. Sem o ``duti``
  instalado, não há como fazer isso de dentro do processo sem ``pyobjc`` — que
  não é dependência do projeto —, então o caminho honesto é orientar, e usar o
  ``duti`` quando ele estiver presente.

Diferente do Windows e do Linux, aqui "aparecer em Abrir com" não depende de
nada que o app faça: acontece sozinho ao abrir o bundle uma vez.
"""

from __future__ import annotations

import logging
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from edgemd.association.common import (
    APP_BUNDLE_ID,
    MIME_TYPES,
    AssociationError,
    AssociationStatus,
    build_command,
)

log = logging.getLogger(__name__)

#: O macOS nao usa template de comando: o LaunchServices entrega o
#: arquivo direto ao aplicativo. O marcador fica para diagnostico.
FILE_PLACEHOLDER = '"%1"'


def is_supported() -> bool:
    """True nesta plataforma. Verificado a cada chamada, não no import."""
    return sys.platform == "darwin"


def _executable_path() -> Path:
    """Caminho do executável em execução.

    Isolado numa função para os testes poderem apontar para um bundle falso sem
    mexer em ``sys.executable``, que é global e afetaria o resto da suíte.
    """
    return Path(sys.executable).resolve()

#: Extensões de arquivo que o bundle declara. O macOS associa por tipo de
#: conteúdo (UTI), mas declarar as extensões garante que arquivos sem tipo
#: reconhecido também caiam aqui.
DOCUMENT_EXTENSIONS = ("md", "markdown", "mdown", "mkd", "mkdn")

#: UTIs do Markdown. ``net.daringfireball.markdown`` é a canônica, adotada por
#: quase todos os editores do sistema.
DOCUMENT_UTIS = (
    "net.daringfireball.markdown",
    "public.plain-text",
)


def bundle_path() -> Path | None:
    """Caminho do ``.app`` em execução, ou None quando não é um bundle.

    O executável de um bundle fica em ``EdgeMD.app/Contents/MacOS/``; subir três
    níveis a partir dele chega na raiz do ``.app``.
    """
    if not is_supported():
        return None

    executavel = _executable_path()
    for pai in executavel.parents:
        if pai.suffix == ".app":
            return pai
    return None


def info_plist_path() -> Path | None:
    bundle = bundle_path()
    if bundle is None:
        return None
    caminho = bundle / "Contents" / "Info.plist"
    return caminho if caminho.is_file() else None


def read_info_plist() -> dict:
    """Lê o ``Info.plist`` do bundle em execução. Vazio se não houver."""
    caminho = info_plist_path()
    if caminho is None:
        return {}
    try:
        with caminho.open("rb") as arquivo:
            return plistlib.load(arquivo)
    except (OSError, plistlib.InvalidFileException) as exc:
        log.warning("Não foi possível ler %s: %s", caminho, exc)
        return {}


def declares_document_types(plist: dict | None = None) -> bool:
    """True se o bundle se declara capaz de abrir Markdown.

    É a verificação que importa no macOS: sem ``CFBundleDocumentTypes`` com as
    UTIs certas, o sistema nunca oferece o app, por mais que o usuário procure.
    """
    dados = plist if plist is not None else read_info_plist()
    tipos = dados.get("CFBundleDocumentTypes") or []

    for entrada in tipos:
        if not isinstance(entrada, dict):
            continue
        conteudos = set(entrada.get("LSItemContentTypes") or [])
        if conteudos & set(DOCUMENT_UTIS):
            return True
        extensoes = set(entrada.get("CFBundleTypeExtensions") or [])
        if extensoes & set(DOCUMENT_EXTENSIONS):
            return True
    return False


def duti_available() -> bool:
    return shutil.which("duti") is not None


def default_handler(uti: str = DOCUMENT_UTIS[0]) -> str | None:
    """Qual bundle está associado a um tipo, segundo o ``duti``.

    Sem o ``duti`` não há consulta: o LaunchServices não expõe isso por linha
    de comando, e ler o ``com.apple.LaunchServices`` exigiria ``pyobjc``.
    """
    if not duti_available():
        return None
    try:
        resultado = subprocess.run(
            ["duti", "-x", uti], capture_output=True, text=True, check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    # A saída é "<caminho>.app:\n  bundle id: <id>"; a segunda linha interessa.
    for linha in resultado.stdout.splitlines():
        if "bundle id:" in linha:
            return linha.split("bundle id:")[-1].strip()
    return resultado.stdout.strip() or None


def status(
    launcher: list[str] | None = None, icon_file: str | Path | None = None
) -> AssociationStatus:
    """Lê o estado atual da associação."""
    if not is_supported():
        return AssociationStatus(
            supported=False, is_default=False, in_open_with=False,
            detail="Associação por bundle só existe no macOS.",
        )

    bundle = bundle_path()
    if bundle is None:
        return AssociationStatus(
            supported=True,
            is_default=False,
            in_open_with=False,
            command=build_command(launcher, FILE_PLACEHOLDER) if launcher else None,
            registered_command=None,
            detail=(
                "Rodando fora de um bundle .app: o macOS só oferece o programa "
                "na lista de \"Abrir com\" a partir do aplicativo empacotado."
            ),
        )

    declarado = declares_document_types()
    padrao = default_handler() == APP_BUNDLE_ID

    detalhe = f"Bundle: {bundle.name}"
    if not declarado:
        detalhe += " — sem CFBundleDocumentTypes no Info.plist"
    elif not duti_available():
        detalhe += " — instale o duti para definir o padrão por linha de comando"

    return AssociationStatus(
        supported=True,
        is_default=padrao,
        # No macOS, estar em um bundle que se declara capaz já basta: o sistema
        # monta a lista de "Abrir com" a partir disso.
        in_open_with=declarado,
        command=None,
        registered_command=APP_BUNDLE_ID if declarado else None,
        detail=detalhe,
    )


def register(
    launcher: list[str],
    icon_file: str | Path | None = None,
    *,
    make_default: bool = True,
) -> AssociationStatus:
    """Verifica o bundle e, se possível, define o app como padrão.

    Não há o que gravar: a declaração de tipos vive no ``Info.plist``, gerado no
    empacotamento. O que se pode fazer aqui é conferir se ela existe e usar o
    ``duti`` para assumir o padrão.
    """
    if not is_supported():
        raise AssociationError("Associação por bundle só existe no macOS.")

    bundle = bundle_path()
    if bundle is None:
        raise AssociationError(
            "O EdgeMD precisa estar empacotado como aplicativo (.app) para o "
            "macOS associá-lo a arquivos Markdown.\n\n"
            "Rode o empacotamento e abra o EdgeMD.app uma vez."
        )

    if not declares_document_types():
        raise AssociationError(
            "O Info.plist deste bundle não declara CFBundleDocumentTypes para "
            "Markdown, então o macOS não vai oferecer o EdgeMD.\n\n"
            "Gere o bundle novamente com o spec do projeto."
        )

    if make_default and duti_available():
        for uti in DOCUMENT_UTIS:
            try:
                subprocess.run(
                    ["duti", "-s", APP_BUNDLE_ID, uti, "all"],
                    capture_output=True, text=True, check=False, timeout=20,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                log.debug("duti falhou para %s: %s", uti, exc)

    return status(launcher, icon_file)


def unregister() -> None:
    """No macOS não há registro a desfazer.

    Os tipos são declarados pelo bundle; apagar o ``.app`` já remove o app da
    lista de "Abrir com". O que se pode fazer é devolver o padrão ao sistema,
    quando o ``duti`` está disponível.
    """
    if not is_supported():
        raise AssociationError("Associação por bundle só existe no macOS.")

    if not duti_available():
        log.info(
            "Sem duti: nada a desfazer. Apagar o EdgeMD.app remove o app da "
            "lista de aplicativos."
        )
        return

    for uti in DOCUMENT_UTIS:
        try:
            subprocess.run(
                ["duti", "-s", "com.apple.TextEdit", uti, "all"],
                capture_output=True, text=True, check=False, timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    log.info("Padrão devolvido ao sistema.")


def instructions() -> str:
    if bundle_path() is None:
        return (
            "O EdgeMD não está rodando de um bundle .app.\n\n"
            "No macOS, a associação vem do Info.plist dentro do aplicativo, "
            "então é preciso empacotar primeiro (veja a seção de "
            "empacotamento) e abrir o EdgeMD.app uma vez."
        )

    texto = (
        "O EdgeMD já aparece em \"Abrir com\" — o macOS lê isso do próprio "
        "aplicativo, sem precisar registrar nada.\n\n"
        "Para torná-lo padrão, use Finder → botão direito no arquivo → "
        "Obter informações → \"Abrir com\" → Alterar tudo."
    )
    if not duti_available():
        texto += (
            "\n\nCom o duti instalado (brew install duti), o próprio EdgeMD "
            "consegue definir isso sozinho."
        )
    return texto
