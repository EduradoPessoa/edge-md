"""Tipos e utilidades comuns aos backends de associação de arquivos.

Cada sistema resolve "abrir .md com este programa" de um jeito bem diferente, e
tentar unificar demais produzia um emaranhado de condicionais. O que se
compartilha aqui é só o vocabulário: o que é um estado, o que é uma falha, e
como montar a linha de comando.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Extensões associadas. A ordem importa no Windows: a primeira é a que o
#: status consulta.
EXTENSIONS = (".md", ".markdown", ".mdown", ".mkd", ".mkdn")

#: Nome exibido ao usuário nos diálogos do sistema.
APP_FRIENDLY_NAME = "EdgeMD"

#: Identificador do aplicativo, em forma de domínio invertido.
#:
#: Usado como ``CFBundleIdentifier`` no bundle do macOS e como nome do
#: ``.desktop`` no Linux. A forma ``io.github.<usuário>.<app>`` é a convenção
#: para projetos de código aberto que não têm domínio próprio.
APP_BUNDLE_ID = "io.github.eduradopessoa.edgemd"

#: Nome do arquivo ``.desktop`` no Linux e do executável empacotado.
DESKTOP_ID = "edgemd.desktop"
EXECUTABLE_NAME = "edgemd.exe" if __import__("sys").platform == "win32" else "edgemd"

#: Tipos MIME que representam Markdown no Linux.
#:
#: Os dois circulam: ``text/markdown`` é o registrado no shared-mime-info
#: moderno, e ``text/x-markdown`` aparece em sistemas mais antigos e em alguns
#: aplicativos. Associar só um deixa metade dos arquivos sem o programa.
MIME_TYPES = ("text/markdown", "text/x-markdown")


class AssociationError(RuntimeError):
    """Falha ao ler ou gravar a associação de arquivos."""


@dataclass(frozen=True)
class AssociationStatus:
    """Situação atual da associação, para mostrar ao usuário.

    Os mesmos campos valem nos três sistemas, mas o significado de "abrir com"
    muda: no Windows é uma lista de programas candidatos; no Linux é
    ``MimeType=`` no arquivo ``.desktop``; no macOS o próprio bundle se declara
    capaz, e o sistema mantém a lista.
    """

    supported: bool
    is_default: bool
    in_open_with: bool
    command: str | None = None
    registered_command: str | None = None
    detail: str = ""

    @property
    def needs_update(self) -> bool:
        """True quando o registro aponta para um comando diferente do atual.

        Acontece quando o app é movido de pasta, ou quando o código-fonte passa
        a rodar de outro lugar.
        """
        if not self.registered_command or not self.command:
            return False
        return self.registered_command != self.command

    @property
    def is_ours(self) -> bool:
        return self.is_default or self.in_open_with


def quote(value: str) -> str:
    """Cita um caminho para linha de comando, se ainda não estiver citado."""
    value = value.strip()
    if value.startswith('"'):
        return value
    return f'"{value}"'


def build_command(launcher: list[str], placeholder: str = "%1") -> str:
    """Monta a linha de comando que o sistema executa ao abrir um arquivo.

    ``placeholder`` é o marcador do arquivo clicado, e vai **como está** — cada
    plataforma decide se ele precisa de aspas:

    * **Windows** usa ``"%1"``, com aspas: sem elas, um caminho com espaço
      ("Meus Documentos\\nota.md") chegaria partido em dois argumentos.
    * **Linux** usa ``%F``, sem aspas: a especificação do ``.desktop`` expande o
      campo já tratando o agrupamento, e citar transformaria todos os arquivos
      num argumento só.
    """
    partes = [quote(parte) for parte in launcher]
    return " ".join(partes) + f" {placeholder}"


def extension_list() -> str:
    """Extensões separadas por vírgula, para mensagens ao usuário."""
    return ", ".join(EXTENSIONS)
