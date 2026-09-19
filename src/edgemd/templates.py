"""Modelos para novos documentos.

Guardados como arquivos ``.md`` numa pasta do usuário, e não como registros
num banco ou num JSON. A escolha é deliberada: um modelo é texto, e o melhor
editor de modelos para um app de Markdown é o próprio app — o usuário abre,
ajusta e salva, com realce de sintaxe e pré-visualização, sem precisar aprender
nenhum formato.

A pasta fica ao lado das preferências (``%APPDATA%`` no Windows,
``~/.config`` no Linux, ``~/Library`` no macOS), então sobrevive a atualizações
e não se mistura com os documentos.

Os modelos **embutidos** existem para o app não abrir sem nada na primeira vez.
Eles não ficam em disco: aparecem na lista, e salvar um deles cria uma cópia
editável na pasta do usuário.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

#: Sufixo dos arquivos de modelo.
SUFFIX = ".md"

#: Caracteres que não podem entrar no nome de um arquivo, em nenhum sistema.
#: A barra e a contrabarra são separadores; os dois-pontos e o asterisco são
#: proibidos no Windows; o resto evita surpresa em sincronização de arquivos.
_INVALIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

#: Nome do arquivo do modelo em branco. Não é gravado em disco, mas precisa de
#: um identificador estável para o config guardar qual é o padrão.
BLANK_NAME = ""


@dataclass(frozen=True)
class Template:
    """Um modelo, embutido ou do usuário."""

    name: str
    content: str
    description: str = ""
    path: Path | None = None

    @property
    def is_builtin(self) -> bool:
        """True quando vem com o app e não pode ser editado nem removido."""
        return self.path is None

    @property
    def editable(self) -> bool:
        return self.path is not None

    def first_line(self) -> str:
        """Primeira linha com conteúdo, para prévia curta."""
        for linha in self.content.splitlines():
            if linha.strip():
                return linha.strip()[:80]
        return ""


# --------------------------------------------------------------------------
# Modelos embutidos
# --------------------------------------------------------------------------

BUILTIN: dict[str, tuple[str, str]] = {
    "Nota de reunião": (
        "Registro de reunião, com pauta, decisões e ações.",
        """# Reunião — {assunto}

**Data:** {data}
**Participantes:**

## Pauta

1.
2.

## Discussão

## Decisões

-

## Ações

- [ ] **@responsável** — tarefa até {data}
""",
    ),
    "Documentação de projeto": (
        "Estrutura de README, com o que o projeto faz e como rodar.",
        """# Nome do projeto

Uma frase dizendo o que ele faz e para quem.

## Instalação

```bash
git clone <url>
cd <projeto>
```

## Uso

```bash
<comando>
```

## Como funciona

## Limitações

## Licença
""",
    ),
    "Artigo": (
        "Post ou artigo, com título, introdução e seções.",
        """# Título do artigo

Uma introdução que diz do que se trata e por que importa.

## Primeira seção

## Segunda seção

### Um detalhe

## Conclusão
""",
    ),
    "Diário": (
        "Entrada de diário ou registro de aprendizado do dia.",
        """# {data}

## O que fiz

## O que aprendi

## O que ficou pendente

- [ ]
""",
    ),
    "Apresentação de ideia": (
        "Proposta com problema, solução, riscos e próximos passos.",
        """# Proposta — {assunto}

## Problema

Qual dor existe hoje, e para quem.

## Solução proposta

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
|  |  |

## Riscos

## Próximos passos

- [ ]
""",
    ),
}


# --------------------------------------------------------------------------
# Pasta do usuário
# --------------------------------------------------------------------------

def templates_dir() -> Path:
    """Pasta dos modelos do usuário, criada se não existir.

    Usa o diretório de configuração do sistema em vez de uma pasta dentro da
    instalação: uma atualização do app não pode levar os modelos junto, e no
    Linux a instalação pode ser somente-leitura.
    """
    from PyQt6.QtCore import QStandardPaths

    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation
    )
    pasta = (Path(base) if base else Path.home() / ".edgemd") / "templates"
    try:
        pasta.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("Não foi possível criar a pasta de modelos %s: %s", pasta, exc)
    return pasta


def safe_filename(name: str) -> str:
    """Converte um nome de modelo num nome de arquivo seguro.

    Um nome como "Ata: 2026/01" viraria um caminho com subpasta no Windows, e
    gravaria no lugar errado — ou falharia sem explicação.

    Um nome feito só de caracteres proibidos (``///``) viraria ``---``, que é
    um arquivo válido mas sem significado nenhum. Nesse caso sobra "modelo".
    """
    limpo = _INVALIDOS.sub("-", name).strip().strip(".")
    limpo = re.sub(r"\s+", " ", limpo)

    # Precisa sobrar alguma letra ou número para o nome dizer alguma coisa.
    if not re.search(r"[^\W_]", limpo, re.UNICODE):
        return "modelo"
    return limpo


def template_path(name: str) -> Path:
    return templates_dir() / f"{safe_filename(name)}{SUFFIX}"


# --------------------------------------------------------------------------
# Leitura
# --------------------------------------------------------------------------

def _read_template(caminho: Path) -> Template | None:
    from edgemd.render import read_text_file

    try:
        conteudo, _encoding, _eol = read_text_file(caminho)
    except OSError as exc:
        log.warning("Não foi possível ler o modelo %s: %s", caminho, exc)
        return None

    return Template(
        name=caminho.stem,
        content=conteudo,
        description="Modelo do usuário",
        path=caminho,
    )


def user_templates() -> list[Template]:
    """Modelos da pasta do usuário, em ordem alfabética."""
    pasta = templates_dir()
    if not pasta.is_dir():
        return []

    encontrados: list[Template] = []
    for caminho in sorted(pasta.glob(f"*{SUFFIX}"), key=lambda p: p.stem.lower()):
        if not caminho.is_file():
            continue
        modelo = _read_template(caminho)
        if modelo is not None:
            encontrados.append(modelo)
    return encontrados


def builtin_templates() -> list[Template]:
    """Modelos que vêm com o app, na ordem em que foram declarados."""
    return [
        Template(name=nome, content=conteudo, description=descricao)
        for nome, (descricao, conteudo) in BUILTIN.items()
    ]


def all_templates(*, include_blank: bool = True) -> list[Template]:
    """Todos os modelos disponíveis.

    Os do usuário vêm primeiro: quem criou um modelo quer usá-lo, e não
    procurá-lo embaixo dos que já vinham no app.

    ``include_blank`` põe o documento em branco no topo, que é o que o
    ``Ctrl+N`` faz quando nenhum modelo está escolhido.
    """
    modelos: list[Template] = []
    if include_blank:
        modelos.append(Template(name="Em branco", content="", description="Documento vazio"))
    modelos.extend(user_templates())
    modelos.extend(builtin_templates())
    return modelos


def find(name: str) -> Template | None:
    """Modelo pelo nome, ou None.

    Nome vazio devolve um modelo em branco — é assim que a preferência "sem
    modelo" é representada, sem precisar de um caso especial no chamador.

    A comparação passa por :func:`safe_filename`, porque o nome do arquivo é a
    versão saneada: procurar por "Ata: 2026" precisa achar o arquivo
    ``Ata- 2026.md``. Sem isso, salvar com um nome que contém caractere
    proibido não detectaria o conflito e sobrescreveria em silêncio.
    """
    if not name:
        return Template(name="Em branco", content="", description="Documento vazio")

    procurado = safe_filename(name).lower()

    for modelo in user_templates():
        if modelo.name.lower() == procurado:
            return modelo
    for modelo in builtin_templates():
        if modelo.name.lower() == name.strip().lower():
            return modelo
    return None


def exists(name: str) -> bool:
    return find(name) is not None


# --------------------------------------------------------------------------
# Escrita
# --------------------------------------------------------------------------

def save(name: str, content: str) -> Path:
    """Grava um modelo na pasta do usuário. Devolve o caminho.

    Um nome que já existe é sobrescrito: é o que se espera ao escolher "Salvar"
    depois de editar um modelo. Quem não quer sobrescrever troca o nome.
    """
    pasta = templates_dir()
    destino = pasta / f"{safe_filename(name)}{SUFFIX}"

    if not content.endswith("\n"):
        content += "\n"

    # newline="" evita a tradução automática do Python, que transformaria cada
    # "\n" em "\r\n" no Windows. Modelos com fim de linha fixo são previsíveis:
    # o mesmo arquivo tem o mesmo conteúdo em qualquer sistema, o que importa
    # para quem sincroniza a pasta de modelos entre máquinas.
    with destino.open("w", encoding="utf-8", newline="") as arquivo:
        arquivo.write(content)

    log.info("Modelo gravado em %s", destino)
    return destino


def delete(name: str) -> bool:
    """Remove um modelo do usuário.

    Modelo embutido não tem arquivo e não pode ser removido — devolve False em
    vez de fingir que removeu.
    """
    for modelo in user_templates():
        if modelo.name == name and modelo.path is not None:
            try:
                modelo.path.unlink()
                log.info("Modelo removido: %s", modelo.path)
                return True
            except OSError as exc:
                log.warning("Não foi possível remover %s: %s", modelo.path, exc)
                return False
    return False


def rename(old_name: str, new_name: str) -> bool:
    """Renomeia um modelo do usuário."""
    origem = None
    for modelo in user_templates():
        if modelo.name == old_name and modelo.path is not None:
            origem = modelo.path
            break
    if origem is None:
        return False

    destino = template_path(new_name)
    if destino == origem:
        return True
    if destino.exists():
        return False

    try:
        origem.rename(destino)
        return True
    except OSError as exc:
        log.warning("Não foi possível renomear %s: %s", origem, exc)
        return False


# --------------------------------------------------------------------------
# Expansão
# --------------------------------------------------------------------------

def expand(content: str, *, title: str = "") -> tuple[str, int]:
    """Substitui os marcadores de data e hora no conteúdo.

    Marcadores simples em vez de uma linguagem de template: o que se quer é
    "a data de hoje", e um motor completo só criaria sintaxe para o usuário
    aprender e erros para depurar.

    Devolve ``(texto, cursor)``, onde ``cursor`` é a posição onde o cursor deve
    ficar — no primeiro marcador de preenchimento, para o usuário começar a
    digitar ali em vez de caçar o lugar.
    """
    from datetime import datetime

    agora = datetime.now()
    substituicoes = {
        "{data}": agora.strftime("%d/%m/%Y"),
        "{hora}": agora.strftime("%H:%M"),
        "{data_iso}": agora.strftime("%Y-%m-%d"),
        "{data_hora}": agora.strftime("%d/%m/%Y %H:%M"),
        "{assunto}": title or "assunto",
        "{titulo}": title or "Título",
    }

    texto = content
    for marcador, valor in substituicoes.items():
        texto = texto.replace(marcador, valor)

    return texto, _cursor_position(texto)


#: Onde o cursor deve parar: o primeiro marcador de preenchimento que sobrou.
#: Os modelos trazem linhas vazias justamente para receber o texto.
_PREENCHIMENTO = re.compile(r"^(\s*(?:[-*]\s*\[[ ]\]|[-*+]|\d+[.)]|>)?\s*)$", re.MULTILINE)


def _cursor_position(texto: str) -> int:
    """Primeira linha vazia que não seja a última, ou o fim do texto.

    Um modelo começa com título e depois uma linha em branco; é ali que o
    usuário quer o cursor.
    """
    linhas = texto.splitlines(keepends=True)
    posicao = 0
    for indice, linha in enumerate(linhas):
        conteudo = linha.rstrip("\r\n")
        if indice > 0 and not conteudo.strip():
            return posicao
        posicao += len(linha)
    return len(texto)
