"""Associação de arquivos no Linux, por arquivo ``.desktop`` e tipos MIME.

O Linux não tem registro central. A associação vive em três lugares:

1. **``~/.local/share/applications/edgemd.desktop``** — diz ao sistema que o
   programa existe, e a linha ``MimeType=`` declara de que tipos ele é capaz.
   Só isso já o coloca em "Abrir com".
2. **``~/.local/share/icons/hicolor/<tamanho>/apps/``** — os ícones, nos
   tamanhos que os ambientes gráficos procuram.
3. **``xdg-mime default``** — torna o programa o padrão do tipo MIME. Escreve
   em ``~/.config/mimeapps.list``, que é o arquivo consultado primeiro.

Os bancos de dados de atalhos e de MIME precisam ser reconstruídos depois
(``update-desktop-database`` e ``update-mime-database``); sem isso o item novo
só aparece depois de reiniciar a sessão. Falhar nesse passo não é fatal — os
arquivos já estão no lugar —, então o erro vira aviso no log.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from edgemd.association.common import (
    APP_FRIENDLY_NAME,
    DESKTOP_ID,
    EXTENSIONS,
    MIME_TYPES,
    AssociationError,
    AssociationStatus,
    build_command,
)

log = logging.getLogger(__name__)

def is_supported() -> bool:
    """True nesta plataforma.

    Verificado a cada chamada, e não no import: um valor fixado no import não
    pode ser exercitado por teste rodando em outra plataforma, o que obrigaria
    a suíte a passar por três máquinas para cobrir os três backends.
    """
    return sys.platform.startswith("linux")

#: Tamanhos de ícone instalados. O ambiente gráfico escolhe o mais próximo.
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

#: Marcador de arquivo no ``Exec=``. ``%F`` aceita vários de uma vez: o
#: gerenciador de arquivos abre toda a seleção numa chamada só, e a instância
#: única distribui entre abas.
PLACEHOLDER = "%F"

#: Nome do arquivo de ícone instalado, sem extensão.
ICON_NAME = "edgemd"

DESKTOP_TEMPLATE = """[Desktop Entry]
Type=Application
Version=1.0
Name={name}
GenericName=Leitor de Markdown
Comment=Leia e edite arquivos Markdown
Exec={exec_line}
Icon={icon_name}
Terminal=false
Categories=Utility;TextEditor;Office;
MimeType={mime};
StartupNotify=true
StartupWMClass=EdgeMD
Keywords=markdown;md;texto;editor;leitor;
"""


def _data_home() -> Path:
    """``$XDG_DATA_HOME``, com o padrão da especificação.

    Lido a cada chamada, e não uma vez no import: os testes apontam a variável
    para uma pasta temporária, e um valor capturado no import ignoraria isso.
    """
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def desktop_path() -> Path:
    return _data_home() / "applications" / DESKTOP_ID


def mimeapps_path() -> Path:
    return _config_home() / "mimeapps.list"


def icon_dir(size: int) -> Path:
    return _data_home() / "icons" / "hicolor" / f"{size}x{size}" / "apps"


def _run(command: list[str]) -> bool:
    """Executa um utilitário do sistema, se existir. Nunca levanta."""
    if shutil.which(command[0]) is None:
        log.debug("%s não está instalado; pulando.", command[0])
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


def default_handler(mime: str) -> str | None:
    """Qual ``.desktop`` está associado a um tipo MIME, segundo o ``xdg-mime``."""
    if shutil.which("xdg-mime") is None:
        return _default_from_mimeapps(mime)

    try:
        resultado = subprocess.run(
            ["xdg-mime", "query", "default", mime],
            capture_output=True, text=True, check=False, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return _default_from_mimeapps(mime)

    valor = resultado.stdout.strip()
    return valor or _default_from_mimeapps(mime)


def _default_from_mimeapps(mime: str) -> str | None:
    """Lê o ``mimeapps.list`` direto.

    Serve de reserva quando o ``xdg-mime`` não existe — comum em instalações
    mínimas — e também para os testes, que não podem depender do utilitário.
    """
    caminho = mimeapps_path()
    if not caminho.is_file():
        return None

    secao = None
    try:
        linhas = caminho.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    for linha in linhas:
        linha = linha.strip()
        if linha.startswith("[") and linha.endswith("]"):
            secao = linha[1:-1]
            continue
        if secao != "Default Applications" or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        if chave.strip() == mime:
            # Pode haver vários separados por ponto e vírgula; o primeiro vale.
            primeiro = valor.split(";")[0].strip()
            if primeiro:
                return primeiro
    return None


def status(
    launcher: list[str] | None = None, icon_file: str | Path | None = None
) -> AssociationStatus:
    """Lê o estado atual da associação."""
    if not is_supported():
        return AssociationStatus(
            supported=False, is_default=False, in_open_with=False,
            detail="Associação por .desktop só existe no Linux.",
        )

    registro = desktop_path()
    existe = registro.is_file()

    registrado_comando = None
    if existe:
        registrado_comando = _exec_line_from_desktop(registro)

    comando = build_command(launcher, PLACEHOLDER) if launcher else None
    padrao = default_handler(MIME_TYPES[0]) == DESKTOP_ID

    detalhe = "Sessão reiniciada pode ser necessária" if existe else ""
    return AssociationStatus(
        supported=True,
        is_default=padrao,
        # No Linux, existir o .desktop com o MimeType é o que coloca o programa
        # na lista de "Abrir com".
        in_open_with=existe,
        command=comando,
        registered_command=registrado_comando,
        detail=detalhe,
    )


def _exec_line_from_desktop(caminho: Path) -> str | None:
    try:
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            if linha.startswith("Exec="):
                return linha[len("Exec="):].strip()
    except OSError:
        return None
    return None


def register(
    launcher: list[str],
    icon_file: str | Path | None = None,
    *,
    make_default: bool = True,
) -> AssociationStatus:
    """Instala o ``.desktop``, os ícones e, se pedido, define como padrão."""
    if not is_supported():
        raise AssociationError("Associação por .desktop só existe no Linux.")

    exec_line = build_command(launcher, PLACEHOLDER)

    registro = desktop_path()
    try:
        registro.parent.mkdir(parents=True, exist_ok=True)
        registro.write_text(
            DESKTOP_TEMPLATE.format(
                name=APP_FRIENDLY_NAME,
                exec_line=exec_line,
                icon_name=ICON_NAME,
                mime=";".join(MIME_TYPES),
            ),
            encoding="utf-8",
        )
        registro.chmod(0o755)
    except OSError as exc:
        raise AssociationError(
            f"Não foi possível gravar {registro}: {exc}"
        ) from exc

    _install_icons(icon_file)

    if make_default:
        # Sem `xdg-mime`, o mimeapps.list é escrito à mão: é o mesmo arquivo,
        # e é o que o sistema consulta de fato.
        feito = _run(
            ["xdg-mime", "default", DESKTOP_ID, *MIME_TYPES]
        )
        if not feito:
            _write_mimeapps_default()

    _refresh_databases()

    log.info("Associação Linux registrada com o comando: %s", exec_line)
    return status(launcher, icon_file)


def _write_mimeapps_default() -> None:
    """Grava a associação padrão direto no ``mimeapps.list``."""
    caminho = mimeapps_path()
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        conteudo = caminho.read_text(encoding="utf-8") if caminho.is_file() else ""
        conteudo = _set_defaults_section(conteudo)
        caminho.write_text(conteudo, encoding="utf-8")
    except OSError as exc:
        log.warning("Não foi possível gravar %s: %s", caminho, exc)


def _set_defaults_section(conteudo: str) -> str:
    """Insere ou atualiza as linhas de tipo MIME em ``[Default Applications]``."""
    linhas = conteudo.splitlines()
    desejadas = {mime: DESKTOP_ID for mime in MIME_TYPES}

    saida: list[str] = []
    dentro = False
    secao_vista = False
    escritas: set[str] = set()

    for linha in linhas:
        crua = linha.strip()
        if crua.startswith("[") and crua.endswith("]"):
            if dentro:
                # Terminando a seção: falta escrever as chaves que não existiam.
                for mime, valor in desejadas.items():
                    if mime not in escritas:
                        saida.append(f"{mime}={valor}")
            dentro = crua == "[Default Applications]"
            secao_vista = secao_vista or dentro
            saida.append(linha)
            continue

        if not dentro or "=" not in crua:
            saida.append(linha)
            continue

        chave = crua.partition("=")[0].strip()
        if chave in desejadas:
            saida.append(f"{chave}={desejadas[chave]}")
            escritas.add(chave)
        else:
            saida.append(linha)

    if dentro:
        for mime, valor in desejadas.items():
            if mime not in escritas:
                saida.append(f"{mime}={valor}")
    elif not secao_vista:
        if saida and saida[-1].strip():
            saida.append("")
        saida.append("[Default Applications]")
        for mime, valor in desejadas.items():
            saida.append(f"{mime}={valor}")

    return "\n".join(saida).rstrip("\n") + "\n"


def _install_icons(icon_file: str | Path | None) -> None:
    """Copia o PNG do app para os diretórios de ícone do tema hicolor."""
    origem = Path(icon_file) if icon_file else None
    if origem is None or not origem.is_file():
        from edgemd.paths import icon_path

        candidato = icon_path("edgemd.png")
        origem = candidato if candidato.is_file() else None

    if origem is None:
        log.info("Sem PNG do ícone; instalando o .desktop sem ícone próprio.")
        return

    try:
        from PIL import Image
    except ImportError:
        # Sem Pillow não dá para gerar os tamanhos; o PNG grande serve, e o
        # ambiente gráfico reduz.
        log.info("Pillow ausente; instalando só o tamanho original do ícone.")
        destino = icon_dir(256) / f"{ICON_NAME}.png"
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origem, destino)
        except OSError as exc:
            log.warning("Não foi possível instalar o ícone: %s", exc)
        return

    try:
        imagem = Image.open(origem).convert("RGBA")
        for size in ICON_SIZES:
            destino = icon_dir(size) / f"{ICON_NAME}.png"
            destino.parent.mkdir(parents=True, exist_ok=True)
            imagem.resize((size, size), Image.LANCZOS).save(destino, "PNG")
    except (OSError, ValueError) as exc:
        log.warning("Não foi possível gerar os ícones: %s", exc)


def _refresh_databases() -> None:
    _run(
        ["update-desktop-database", str(_data_home() / "applications")]
    )
    _run(["update-mime-database", str(_data_home() / "mime")])


def unregister() -> None:
    """Remove o ``.desktop``, os ícones e devolve o padrão ao sistema."""
    if not is_supported():
        raise AssociationError("Associação por .desktop só existe no Linux.")

    registro = desktop_path()
    if registro.is_file():
        try:
            registro.unlink()
        except OSError as exc:
            log.warning("Não foi possível remover %s: %s", registro, exc)

    base = _data_home() / "icons" / "hicolor"
    for size in ICON_SIZES:
        alvo = base / f"{size}x{size}" / "apps" / f"{ICON_NAME}.png"
        try:
            alvo.unlink(missing_ok=True)
        except OSError:
            pass

    # Devolve a escolha ao sistema em vez de deixar apontando para um programa
    # que não existe mais.
    for mime in MIME_TYPES:
        if default_handler(mime) == DESKTOP_ID:
            _remove_from_mimeapps(mime)

    _refresh_databases()
    log.info("Associação Linux removida.")


def _remove_from_mimeapps(mime: str) -> None:
    caminho = mimeapps_path()
    if not caminho.is_file():
        return

    linhas = []
    dentro = False
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        crua = linha.strip()
        if crua.startswith("[") and crua.endswith("]"):
            dentro = crua == "[Default Applications]"
            linhas.append(linha)
            continue
        if dentro and crua.partition("=")[0].strip() == mime:
            continue
        linhas.append(linha)

    try:
        caminho.write_text("\n".join(linhas).rstrip("\n") + "\n", encoding="utf-8")
    except OSError as exc:
        log.warning("Não foi possível atualizar %s: %s", caminho, exc)


def instructions() -> str:
    return (
        "O EdgeMD é instalado para o seu usuário, em ~/.local/share, sem "
        "precisar de root.\n\n"
        "Se o item não aparecer no menu \"Abrir com\" logo de cara, saia da "
        "sessão e entre de novo: o ambiente gráfico lê a lista de atalhos ao "
        "iniciar.\n\n"
        "Para conferir ou trocar o padrão, use as preferências do seu ambiente "
        "gráfico ou o comando:\n"
        f"    xdg-mime default {DESKTOP_ID} {' '.join(MIME_TYPES)}"
    )
