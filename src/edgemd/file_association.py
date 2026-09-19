"""Associação de arquivos ``.md`` no registro do Windows.

Tudo é gravado em ``HKEY_CURRENT_USER``, e não em ``HKEY_CLASSES_ROOT``. Isso é
deliberado por dois motivos: não exige privilégio de administrador, e não
mexe na configuração de outros usuários da máquina.

São registradas três camadas, e cada uma serve a um propósito diferente:

1. **``.md\\OpenWithProgids``** — faz o app aparecer no menu "Abrir com" sem
   roubar a associação que o usuário já tinha. Esta é a parte segura e sempre
   aplicada.
2. **``.md`` (padrão)** — torna o app o programa padrão do clique duplo.
   Só é aplicada quando ``make_default=True``, porque sobrescreve uma escolha
   que pode ter sido consciente.
3. **``Capabilities`` + ``RegisteredApplications``** — faz o app aparecer em
   Configurações → Aplicativos → Aplicativos padrão, onde o usuário pode
   promovê-lo a padrão por conta própria. Windows 8 e superiores.

Depois de gravar, é preciso avisar o Shell (``SHChangeNotify``) — sem isso o
Explorer continua mostrando o ícone antigo até reiniciar.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

try:
    import winreg
except ImportError:  # pragma: no cover - só relevante fora do Windows
    winreg = None  # type: ignore[assignment]

#: Identificador do tipo de documento. Não mude depois de publicar: é o que o
#: registro usa para achar o app.
PROG_ID = "EdgeMD.Document"

#: Nome exibido no Explorer e nas Configurações.
FRIENDLY_NAME = "Documento Markdown"
APP_FRIENDLY_NAME = "EdgeMD"

#: Extensões associadas.
EXTENSIONS = (".md", ".markdown", ".mdown", ".mkd", ".mkdn")

CAPABILITIES_PATH = r"Software\EdgeMD\EdgeMD\Capabilities"

#: Nome do executável empacotado. Usado como chave em
#: ``Software\Classes\Applications`` e ao desfazer.
EXECUTABLE_NAME = "edgemd.exe"

#: Constantes do SHChangeNotify.
SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_IDLIST = 0x0000


class AssociationError(RuntimeError):
    """Falha ao ler ou gravar as chaves de associação."""


@dataclass(frozen=True)
class AssociationStatus:
    """Situação atual da associação, para mostrar ao usuário."""

    default_prog_id: str | None
    is_our_default: bool
    in_open_with: bool
    command: str | None
    registered_command: str | None

    @property
    def needs_update(self) -> bool:
        """True quando o registro aponta para um comando diferente do atual.

        Acontece quando o app é movido de pasta, ou quando o código-fonte é
        executado de um lugar diferente do que foi registrado.
        """
        if not self.registered_command:
            return False
        return self.registered_command != self.command


def _require_windows() -> None:
    if winreg is None:
        raise AssociationError(
            "A associação de arquivos só está disponível no Windows."
        )


def _quote(value: str) -> str:
    """Cita um caminho para linha de comando, se ainda não estiver."""
    value = value.strip()
    if value.startswith('"'):
        return value
    return f'"{value}"'


def build_command(launcher: list[str]) -> str:
    """Monta a linha de comando que o Explorer executa.

    ``%1`` é o arquivo clicado. Em seleção múltipla, o Windows invoca o
    programa uma vez por arquivo — o que funciona bem aqui, porque a instância
    única reaproveita a janela já aberta.
    """
    parts = [_quote(part) for part in launcher]
    return " ".join(parts) + ' "%1"'


# --------------------------------------------------------------------------
# Leitura
# --------------------------------------------------------------------------

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

    Necessário porque ``OpenWithProgids`` guarda uma lista de **valores**
    nomeados (um por ProgID), não subchaves. Procurar uma subchave ali devolve
    sempre falso, e foi o que fez o status mentir sobre o registro.
    """
    try:
        with winreg.OpenKey(root, path) as key:
            winreg.QueryValueEx(key, name)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _delete_value(root, path: str, name: str) -> None:
    """Remove um valor nomeado, sem falhar se ele ou a chave não existirem."""
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.debug("Não foi possível remover o valor %s\\%s: %s", path, name, exc)


def status(launcher: list[str] | None = None) -> AssociationStatus:
    """Lê o estado atual das associações.

    A extensão consultada é ``EXTENSIONS[0]``, e não um ``.md`` fixo: a lista
    é configurável, e ler sempre o mesmo literal faria o status mentir em
    qualquer cenário que não fosse o padrão.
    """
    _require_windows()
    root = winreg.HKEY_CURRENT_USER
    primary = EXTENSIONS[0] if EXTENSIONS else ".md"

    default_prog_id = _read_default(root, rf"Software\Classes\{primary}")
    in_open_with = _value_exists(
        root, rf"Software\Classes\{primary}\OpenWithProgids", PROG_ID
    )
    registered_command = _read_default(
        root, rf"Software\Classes\{PROG_ID}\shell\open\command"
    )
    command = build_command(launcher) if launcher else None

    return AssociationStatus(
        default_prog_id=default_prog_id,
        is_our_default=default_prog_id == PROG_ID,
        in_open_with=in_open_with,
        command=command,
        registered_command=registered_command,
    )


# --------------------------------------------------------------------------
# Escrita
# --------------------------------------------------------------------------

def _set_default(root, path: str, value: str) -> None:
    with winreg.CreateKeyEx(root, path, 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, value)


def _set_value(root, path: str, name: str, value: str | bytes, kind: int | None = None) -> None:
    """Grava um valor, com o tipo padrão REG_SZ.

    A checagem é ``is None`` de propósito: ``winreg.REG_NONE`` vale **0**, que
    é falsy, então um ``kind or REG_SZ`` trocaria silenciosamente o tipo para
    REG_SZ — e a gravação de um valor binário falharia com "could not convert
    the data to the specified type".
    """
    if kind is None:
        kind = winreg.REG_SZ
    with winreg.CreateKeyEx(root, path, 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, name, 0, kind, value)


def _delete_key(root, path: str) -> None:
    try:
        winreg.DeleteKeyEx(root, path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        # Chave com subchaves não pode ser removida assim; tentamos recursivo.
        log.debug("Remoção simples de %s falhou (%s); tentando recursivo.", path, exc)
        _delete_tree(root, path)


def _delete_tree(root, path: str) -> None:
    """Remove uma chave e tudo abaixo dela."""
    try:
        with winreg.OpenKey(root, path) as key:
            while True:
                try:
                    subkey = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _delete_tree(root, f"{path}\\{subkey}")
    except FileNotFoundError:
        return
    except OSError:
        return

    try:
        winreg.DeleteKeyEx(root, path)
    except OSError as exc:
        log.debug("Não foi possível remover %s: %s", path, exc)


def register(
    launcher: list[str],
    icon_file: str | Path | None = None,
    *,
    make_default: bool = True,
) -> AssociationStatus:
    """Grava as associações do app. Devolve o estado resultante.

    ``make_default=False`` registra apenas em "Abrir com", sem alterar o
    programa padrão do clique duplo.
    """
    _require_windows()
    root = winreg.HKEY_CURRENT_USER
    command = build_command(launcher)
    icon = str(icon_file) if icon_file else _icon_from_launcher(launcher)

    # 1. Tipo de documento (ProgID).
    _set_default(root, rf"Software\Classes\{PROG_ID}", FRIENDLY_NAME)
    _set_value(root, rf"Software\Classes\{PROG_ID}", "FriendlyTypeName", FRIENDLY_NAME)
    if icon:
        _set_default(root, rf"Software\Classes\{PROG_ID}\DefaultIcon", f"{icon},0")
    _set_default(root, rf"Software\Classes\{PROG_ID}\shell", "open")
    _set_default(root, rf"Software\Classes\{PROG_ID}\shell\open", "")
    _set_default(root, rf"Software\Classes\{PROG_ID}\shell\open\command", command)

    for extension in EXTENSIONS:
        base = rf"Software\Classes\{extension}"
        # Faz o app aparecer em "Abrir com" sem roubar a associação atual.
        _set_value(
            root,
            rf"{base}\OpenWithProgids",
            PROG_ID,
            b"",
            winreg.REG_NONE,
        )
        if make_default:
            _set_default(root, base, PROG_ID)
        # Com make_default=False o valor padrão não é tocado — nem para gravar,
        # nem para apagar. Apagar seria pior: removaria a associação que o
        # usuário já tinha com outro programa, que é exatamente o que este
        # modo existe para evitar.

    # 2. Entrada em "Abrir com → Escolher outro aplicativo".
    #
    #    Esta chave é indexada pelo NOME DO ARQUIVO do executável, porque é
    #    assim que o Windows a procura. Só gravamos quando o launcher é o
    #    nosso próprio executável: rodando do código-fonte ele é o
    #    pythonw.exe, e registrar ``Applications\pythonw.exe`` mudaria como
    #    *todos* os arquivos .pyw do usuário abrem. Não vale o risco por um
    #    item de menu.
    from edgemd.paths import is_frozen

    if is_frozen() and Path(launcher[0]).name.lower() == EXECUTABLE_NAME:
        applications = rf"Software\Classes\Applications\{EXECUTABLE_NAME}"
        _set_default(root, rf"{applications}\shell\open\command", command)
        if icon:
            _set_default(root, rf"{applications}\DefaultIcon", f"{icon},0")
        _set_value(root, applications, "FriendlyAppName", APP_FRIENDLY_NAME)
    else:
        log.info(
            "Rodando do código-fonte: a entrada em Applications não é gravada "
            "para não alterar a associação do interpretador Python."
        )

    # 3. Capabilities: faz o app aparecer nas Configurações do Windows.
    _set_default(root, CAPABILITIES_PATH, APP_FRIENDLY_NAME)
    _set_value(root, CAPABILITIES_PATH, "ApplicationName", APP_FRIENDLY_NAME)
    for extension in EXTENSIONS:
        _set_value(
            root,
            rf"{CAPABILITIES_PATH}\FileAssociations",
            extension,
            PROG_ID,
        )
    _set_value(
        root,
        r"Software\RegisteredApplications",
        APP_FRIENDLY_NAME,
        CAPABILITIES_PATH,
    )

    notify_shell()
    log.info("Associações registradas com o comando: %s", command)
    return status(launcher)


def unregister() -> None:
    """Remove tudo o que :func:`register` criou."""
    _require_windows()
    root = winreg.HKEY_CURRENT_USER

    for extension in EXTENSIONS:
        base = rf"Software\Classes\{extension}"
        # Só desfaz o que é nosso: se o padrão for outro programa, preservamos.
        current = _read_default(root, base)
        if current == PROG_ID:
            _delete_value(root, base, "")
        # OpenWithProgids: removemos o VALOR nomeado, não uma subchave.
        _delete_value(root, rf"{base}\OpenWithProgids", PROG_ID)

    _delete_tree(root, rf"Software\Classes\{PROG_ID}")
    _delete_tree(root, rf"Software\Classes\Applications\{EXECUTABLE_NAME}")
    _delete_tree(root, CAPABILITIES_PATH)

    try:
        with winreg.OpenKey(
            root, r"Software\RegisteredApplications", 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, APP_FRIENDLY_NAME)
    except (FileNotFoundError, OSError):
        pass

    notify_shell()
    log.info("Associações removidas.")


def _icon_from_launcher(launcher: list[str]) -> str | None:
    """Descobre um arquivo de ícone a usar no registro."""
    from edgemd.paths import icon_path

    candidate = icon_path("edgemd.ico")
    if candidate.is_file():
        return str(candidate)

    # Em bundle, o próprio executável carrega o ícone.
    from edgemd.paths import is_frozen

    if is_frozen():
        return launcher[0]
    return None


def notify_shell() -> None:
    """Avisa o Explorer que as associações mudaram.

    Sem isto, ícones e o programa padrão continuam desatualizados até o
    Explorer reiniciar.
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SHChangeNotify(  # type: ignore[attr-defined]
            SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None
        )
    except (AttributeError, OSError) as exc:
        log.debug("SHChangeNotify falhou: %s", exc)
