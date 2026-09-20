"""Associação de arquivos no Windows, pelo registro.

Tudo é gravado em ``HKEY_CURRENT_USER``, e não em ``HKEY_CLASSES_ROOT``. Isso é
deliberado por dois motivos: não exige privilégio de administrador, e não mexe
na configuração de outros usuários da máquina.

São registradas três camadas, cada uma com um propósito:

1. **``.md\\OpenWithProgids``** — faz o app aparecer no menu "Abrir com" sem
   roubar a associação que o usuário já tinha. É a parte segura, sempre aplicada.
2. **``.md`` (padrão)** — torna o app o programa do clique duplo. Só é aplicada
   quando ``make_default=True``, porque sobrescreve uma escolha consciente.
3. **``Capabilities`` + ``RegisteredApplications``** — faz o app aparecer em
   Configurações → Aplicativos → Aplicativos padrão, onde o usuário pode
   promovê-lo sozinho.

Depois de gravar, é preciso avisar o Shell (``SHChangeNotify``) — sem isso o
Explorer continua mostrando o ícone antigo até reiniciar.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path

from edgemd.association.common import (
    APP_FRIENDLY_NAME,
    EXTENSIONS,
    AssociationError,
    AssociationStatus,
    build_command,
)

log = logging.getLogger(__name__)

try:
    import winreg
except ImportError:  # pragma: no cover - só relevante fora do Windows
    winreg = None  # type: ignore[assignment]

#: Identificador do tipo de documento. Não mude depois de publicar: é o que o
#: registro usa para achar o app.
PROG_ID = "EdgeMD.Document"

#: Nome do executável empacotado. Usado como chave em
#: ``Software\\Classes\\Applications`` e ao desfazer.
EXECUTABLE_NAME = "edgemd.exe"

CAPABILITIES_PATH = r"Software\EdgeMD\EdgeMD\Capabilities"

#: Constantes do SHChangeNotify.
SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_IDLIST = 0x0000

#: Marcador do arquivo clicado.
#:
#: Com aspas, ao contrário do Linux: sem elas, um caminho com espaço
#: ("Meus Documentos\nota.md") chegaria ao programa partido em dois argumentos.
FILE_PLACEHOLDER = '"%1"'

def is_supported() -> bool:
    """True nesta plataforma. Verificado a cada chamada, nao no import."""
    return sys.platform == "win32"


#: Mantido para quem ja consultava a constante no import.
SUPPORTED = sys.platform == "win32"

#: Código devolvido pelo Windows quando o processo não pertence a um pacote.
#: O valor é ``APPMODEL_ERROR_NO_PACKAGE``, da API de modelo de aplicativo.
APPMODEL_ERROR_NO_PACKAGE = 15700


def is_packaged() -> bool:
    """True quando o app roda de um pacote MSIX/AppX.

    Muda tudo na associação de arquivos: um pacote MSIX declara os tipos que
    abre no próprio manifesto, e o Windows mantém isso. O registro de um
    processo empacotado é **virtualizado** — uma gravação em ``HKCU`` some
    dentro do pacote e não tem efeito nenhum sobre o sistema, então o app
    pareceria ter funcionado sem ter feito nada.

    A consulta é feita a cada chamada, e não em cache no import: assim os testes
    podem trocar o resultado, e o custo é uma chamada de sistema.
    """
    if sys.platform != "win32":
        return False

    try:
        # A função devolve o tamanho necessário e falha com
        # APPMODEL_ERROR_NO_PACKAGE quando o processo não é empacotado.
        tamanho = ctypes.c_uint32(0)
        resultado = ctypes.windll.kernel32.GetCurrentPackageFullName(  # type: ignore[attr-defined]
            ctypes.byref(tamanho), None
        )
        return resultado != APPMODEL_ERROR_NO_PACKAGE
    except (AttributeError, OSError):
        # GetCurrentPackageFullName só existe do Windows 8 em diante; em
        # sistemas mais antigos a resposta é simplesmente "não é pacote".
        return False


def _require_support() -> None:
    if winreg is None:
        raise AssociationError(
            "A associação pelo registro só existe no Windows."
        )


def _read_default(root, path: str) -> str | None:
    try:
        with winreg.OpenKey(root, path) as key:
            value, _ = winreg.QueryValueEx(key, "")
            return str(value)
    except FileNotFoundError:
        return None
    except OSError as exc:
        log.debug("Falha ao ler %s: %s", path, exc)
        return None


def _key_exists(root, path: str) -> bool:
    try:
        with winreg.OpenKey(root, path):
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _value_exists(root, path: str, name: str) -> bool:
    """True se existe um VALOR chamado ``name`` sob a chave ``path``.

    ``OpenWithProgids`` guarda uma lista de **valores** nomeados, um por
    ProgID, e não subchaves. Procurar uma subchave ali devolve sempre falso.
    """
    try:
        with winreg.OpenKey(root, path) as key:
            winreg.QueryValueEx(key, name)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _set_default(root, path: str, value: str) -> None:
    with winreg.CreateKeyEx(root, path, 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, value)


def _set_value(
    root, path: str, name: str, value: str | bytes, kind: int | None = None
) -> None:
    """Grava um valor, com o tipo padrão REG_SZ.

    A checagem é ``is None`` de propósito: ``winreg.REG_NONE`` vale **0**, que é
    falsy, então um ``kind or REG_SZ`` trocaria o tipo para REG_SZ em silêncio.
    """
    if kind is None:
        kind = winreg.REG_SZ
    with winreg.CreateKeyEx(root, path, 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, name, 0, kind, value)


def _delete_value(root, path: str, name: str) -> None:
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.debug("Não foi possível remover o valor %s\\%s: %s", path, name, exc)


def delete_tree(root, path: str) -> None:
    """Remove uma chave e tudo abaixo dela."""
    try:
        with winreg.OpenKey(root, path) as key:
            while True:
                try:
                    subkey = winreg.EnumKey(key, 0)
                except OSError:
                    break
                delete_tree(root, f"{path}\\{subkey}")
    except FileNotFoundError:
        return
    except OSError:
        return

    try:
        winreg.DeleteKeyEx(root, path)
    except OSError as exc:
        log.debug("Não foi possível remover %s: %s", path, exc)


# --------------------------------------------------------------------------
# Interface
# --------------------------------------------------------------------------

def status(
    launcher: list[str] | None = None, icon_file: str | Path | None = None
) -> AssociationStatus:
    """Lê o estado atual das associações."""
    if not is_supported():
        return AssociationStatus(
            supported=False, is_default=False, in_open_with=False,
            detail="Registro do Windows indisponível nesta plataforma.",
        )

    if is_packaged():
        # Num pacote MSIX não há o que consultar no registro: quem declara os
        # tipos de arquivo é o AppxManifest, e é o Windows que mantém a lista.
        return AssociationStatus(
            supported=True,
            # O app aparece em "Abrir com" por causa da declaração no
            # manifesto, e não por nada que a gente tenha gravado.
            in_open_with=True,
            is_default=False,
            command=None,
            registered_command=None,
            detail=(
                "Pacote MSIX: o Windows gerencia a associação pelo manifesto. "
                "Para tornar padrão, use Abrir com → Escolher outro aplicativo."
            ),
        )

    root = winreg.HKEY_CURRENT_USER
    primaria = EXTENSIONS[0] if EXTENSIONS else ".md"

    default_prog_id = _read_default(root, rf"Software\Classes\{primaria}")
    in_open_with = _value_exists(
        root, rf"Software\Classes\{primaria}\OpenWithProgids", PROG_ID
    )
    registered_command = _read_default(
        root, rf"Software\Classes\{PROG_ID}\shell\open\command"
    )
    command = (
        build_command(launcher, FILE_PLACEHOLDER) if launcher else None
    )

    return AssociationStatus(
        supported=True,
        is_default=default_prog_id == PROG_ID,
        in_open_with=in_open_with,
        command=command,
        registered_command=registered_command,
        detail="Configurações → Aplicativos → Aplicativos padrão",
    )


def _icon_from_launcher(launcher: list[str]) -> str | None:
    from edgemd.paths import icon_path, is_frozen

    candidato = icon_path("edgemd.ico")
    if candidato.is_file():
        return str(candidato)
    if is_frozen():
        return launcher[0]
    return None


def register(
    launcher: list[str],
    icon_file: str | Path | None = None,
    *,
    make_default: bool = True,
) -> AssociationStatus:
    """Grava as associações do app. Devolve o estado resultante."""
    _require_support()

    if is_packaged():
        # Num pacote MSIX o registro é virtualizado por processo: a gravação
        # ficaria dentro do pacote e o sistema não veria nada. Recusar com
        # explicação é melhor do que gravar e relatar sucesso.
        raise AssociationError(
            "O EdgeMD está instalado como pacote MSIX, e nesse formato a "
            "associação de arquivos vem declarada no próprio pacote.\n\n"
            "O Windows já mantém a lista, então não há nada a registrar. "
            "Para tornar o EdgeMD o programa padrão, use botão direito no "
            "arquivo → Abrir com → Escolher outro aplicativo."
        )

    root = winreg.HKEY_CURRENT_USER
    command = build_command(launcher, FILE_PLACEHOLDER)
    icon = str(icon_file) if icon_file else _icon_from_launcher(launcher)

    # 1. Tipo de documento (ProgID).
    _set_default(root, rf"Software\Classes\{PROG_ID}", APP_FRIENDLY_NAME)
    _set_value(
        root, rf"Software\Classes\{PROG_ID}", "FriendlyTypeName", APP_FRIENDLY_NAME
    )
    if icon:
        _set_default(root, rf"Software\Classes\{PROG_ID}\DefaultIcon", f"{icon},0")
    _set_default(root, rf"Software\Classes\{PROG_ID}\shell", "open")
    _set_default(root, rf"Software\Classes\{PROG_ID}\shell\open", "")
    _set_default(root, rf"Software\Classes\{PROG_ID}\shell\open\command", command)

    # 2. Extensões.
    for extension in EXTENSIONS:
        base = rf"Software\Classes\{extension}"
        _set_value(
            root, rf"{base}\OpenWithProgids", PROG_ID, b"", winreg.REG_NONE
        )
        if make_default:
            _set_default(root, base, PROG_ID)
        # Com make_default=False o valor padrão não é tocado — nem para gravar,
        # nem para apagar. Apagar seria pior: removeria a associação que o
        # usuário já tinha com outro programa.

    # 3. Entrada em "Abrir com → Escolher outro aplicativo".
    #
    #    Esta chave é indexada pelo NOME do executável, porque é assim que o
    #    Windows a procura. Só gravamos quando o launcher é o nosso próprio
    #    executável: rodando do código-fonte ele é o pythonw.exe, e registrar
    #    ``Applications\pythonw.exe`` mudaria como *todos* os .pyw do usuário
    #    abrem.
    from edgemd.paths import is_frozen

    if is_frozen() and Path(launcher[0]).name.lower() == EXECUTABLE_NAME:
        aplicacoes = rf"Software\Classes\Applications\{EXECUTABLE_NAME}"
        _set_default(root, rf"{aplicacoes}\shell\open\command", command)
        if icon:
            _set_default(root, rf"{aplicacoes}\DefaultIcon", f"{icon},0")
        _set_value(root, aplicacoes, "FriendlyAppName", APP_FRIENDLY_NAME)
    else:
        log.info(
            "Rodando do código-fonte: a entrada em Applications não é gravada "
            "para não alterar a associação do interpretador Python."
        )

    # 4. Capabilities: faz o app aparecer nas Configurações do Windows.
    _set_default(root, CAPABILITIES_PATH, APP_FRIENDLY_NAME)
    _set_value(root, CAPABILITIES_PATH, "ApplicationName", APP_FRIENDLY_NAME)
    for extension in EXTENSIONS:
        _set_value(
            root, rf"{CAPABILITIES_PATH}\FileAssociations", extension, PROG_ID
        )
    _set_value(
        root,
        r"Software\RegisteredApplications",
        APP_FRIENDLY_NAME,
        CAPABILITIES_PATH,
    )

    notify_shell()
    log.info("Associações registradas com o comando: %s", command)
    return status(launcher, icon_file)


def unregister() -> None:
    """Remove tudo o que :func:`register` criou."""
    _require_support()

    if is_packaged():
        # Não há o que desfazer: a associação vive no manifesto do pacote, e o
        # Windows a remove junto com ele. Apagar as chaves de ProgID seria
        # inofensivo, mas passar a impressão de que "desassociou" seria falso.
        raise AssociationError(
            "O EdgeMD está instalado como pacote MSIX, e a associação de "
            "arquivos faz parte do pacote.\n\n"
            "Para removê-la, desinstale o EdgeMD em Configurações → "
            "Aplicativos → Aplicativos instalados."
        )

    root = winreg.HKEY_CURRENT_USER

    for extension in EXTENSIONS:
        base = rf"Software\Classes\{extension}"
        # Só desfaz o que é nosso: se o padrão for outro programa, preservamos.
        if _read_default(root, base) == PROG_ID:
            _delete_value(root, base, "")
        # OpenWithProgids: removemos o VALOR nomeado, não uma subchave.
        _delete_value(root, rf"{base}\OpenWithProgids", PROG_ID)

    delete_tree(root, rf"Software\Classes\{PROG_ID}")
    delete_tree(root, rf"Software\Classes\Applications\{EXECUTABLE_NAME}")
    delete_tree(root, CAPABILITIES_PATH)

    try:
        with winreg.OpenKey(
            root, r"Software\RegisteredApplications", 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, APP_FRIENDLY_NAME)
    except (FileNotFoundError, OSError):
        pass

    notify_shell()
    log.info("Associações removidas.")


def notify_shell() -> None:
    """Avisa o Explorer que as associações mudaram.

    Sem isto, ícones e o programa padrão continuam desatualizados até o
    Explorer reiniciar.
    """
    if not SUPPORTED:
        return
    try:
        ctypes.windll.shell32.SHChangeNotify(  # type: ignore[attr-defined]
            SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None
        )
    except (AttributeError, OSError) as exc:
        log.debug("SHChangeNotify falhou: %s", exc)


def instructions() -> str:
    if is_packaged():
        return (
            "O EdgeMD está instalado como pacote MSIX, e nesse formato a "
            "associação de arquivos é declarada no próprio pacote — o Windows "
            "a cria e a mantém, sem nada gravado no registro.\n\n"
            "O app já aparece em \"Abrir com\". Para torná-lo padrão, use botão "
            "direito no arquivo → Abrir com → Escolher outro aplicativo, e "
            "marque \"Sempre usar este aplicativo\".\n\n"
            "Desinstalar o EdgeMD em Configurações → Aplicativos remove a "
            "associação junto."
        )

    return (
        "As associações ficam em HKEY_CURRENT_USER, sem pedir administrador.\n\n"
        "Para tornar o EdgeMD padrão, use botão direito no arquivo → "
        "Abrir com → Escolher outro aplicativo, e marque \"Sempre usar este "
        "aplicativo\". O app também aparece em Configurações → Aplicativos → "
        "Aplicativos padrão."
    )
