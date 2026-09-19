"""Preparo do caminho de uma imagem para inserir no documento.

Inserir uma imagem parece trivial — basta escrever ``![](caminho)`` — mas o
caminho é o que decide se o documento continua portátil. Um ``C:\\Users\\...``
absoluto funciona na máquina de quem escreveu e quebra em qualquer outra, e num
repositório isso é pior do que não ter imagem.

A regra aqui:

* imagem já dentro da pasta do documento → caminho relativo, nada é copiado;
* imagem fora → oferece copiar para ``imagens/`` ao lado do ``.md``, e usa o
  caminho relativo da cópia;
* documento ainda sem arquivo salvo → não há relativo possível, então usa o
  caminho absoluto e avisa.

Este módulo não abre janela nenhuma: só decide caminhos e copia arquivos.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

#: Formatos oferecidos no diálogo de escolha e aceitos na cópia.
IMAGE_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico", ".avif",
)

#: Pasta criada ao lado do documento para receber imagens de fora.
DEFAULT_ASSETS_FOLDER = "imagens"

#: Filtro para o diálogo de arquivo do Qt.
FILE_FILTER = (
    "Imagens (" + " ".join(f"*{s}" for s in IMAGE_SUFFIXES) + ");;Todos os arquivos (*)"
)

#: Caracteres que quebram a sintaxe de link do Markdown se ficarem crus.
_ESCAPAR = {
    " ": "%20",
    "#": "%23",
    "?": "%3F",
    "%": "%25",
    "[": "%5B",
    "]": "%5D",
    "<": "%3C",
    ">": "%3E",
}

#: Um único passo de substituição. Percorrer o dicionário em sequência parece
#: mais simples, mas erra: escapar o espaço antes do ``%`` transformaria o
#: ``%20`` recém-criado em ``%2520``. Numa passada só, cada caractere do texto
#: original é visto uma vez e não há como reprocessar o que já foi escrito.
_ESCAPAR_RE = re.compile("|".join(re.escape(c) for c in _ESCAPAR))


@dataclass(frozen=True)
class PreparedImage:
    """Resultado do preparo, pronto para virar ``![alt](url)``."""

    source: Path
    url: str
    alt: str
    copied_to: Path | None = None
    relative: bool = True

    @property
    def was_copied(self) -> bool:
        return self.copied_to is not None


def markdown_url(path: str | Path) -> str:
    """Converte um caminho em URL utilizável dentro do Markdown.

    Barras invertidas viram barras normais, porque ``\\`` é escape no Markdown,
    e os caracteres que quebrariam o link são percent-encoded. Espaços aparecem
    o tempo todo em nomes de pasta no Windows ("Meus Documentos"), então esse é
    o caso que mais importa.
    """
    texto = str(path).replace("\\", "/")
    return _ESCAPAR_RE.sub(lambda m: _ESCAPAR[m.group(0)], texto)


def is_inside(child: Path, parent: Path) -> bool:
    """True se ``child`` está dentro de ``parent`` (ou é igual a ele)."""
    try:
        child.resolve().relative_to(parent.resolve())
    except (ValueError, OSError):
        return False
    return True


def relative_url(target: Path, base_dir: Path) -> str:
    """Caminho de ``target`` relativo a ``base_dir``, em forma de URL."""
    import os

    relativo = os.path.relpath(str(target.resolve()), str(base_dir.resolve()))
    return markdown_url(relativo)


def unique_target(directory: Path, filename: str, source: Path) -> Path:
    """Destino livre para a cópia, sem sobrescrever nada.

    Se já existe um arquivo com esse nome e **o mesmo conteúdo**, ele é
    reaproveitado: inserir a mesma imagem duas vezes não deve encher a pasta de
    ``foto-2.png``, ``foto-3.png``.

    Se o conteúdo for diferente, acrescenta um sufixo numérico até achar um nome
    livre — sobrescrever apagaria uma imagem que o documento já usa.
    """
    candidato = directory / filename
    if not candidato.exists():
        return candidato

    try:
        if candidato.read_bytes() == source.read_bytes():
            return candidato
    except OSError:
        pass

    tronco = Path(filename).stem
    extensao = Path(filename).suffix
    for indice in range(2, 1000):
        candidato = directory / f"{tronco}-{indice}{extensao}"
        if not candidato.exists():
            return candidato

    # Praticamente inalcançável; melhor um nome feio do que sobrescrever.
    raise FileExistsError(f"não achei nome livre para {filename} em {directory}")


def copy_into_document(
    image: Path, document_path: Path, folder: str = DEFAULT_ASSETS_FOLDER
) -> Path:
    """Copia a imagem para a pasta do documento. Devolve o destino."""
    destino_dir = document_path.parent / folder
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = unique_target(destino_dir, image.name, image)
    if destino.exists():
        log.debug("Imagem idêntica já estava em %s", destino)
        return destino

    shutil.copy2(image, destino)
    log.info("Imagem copiada para %s", destino)
    return destino


def prepare_image(
    image: str | Path,
    document_path: str | Path | None,
    *,
    copy_external: bool = True,
    folder: str = DEFAULT_ASSETS_FOLDER,
) -> PreparedImage:
    """Decide o caminho a escrever no documento.

    Levanta ``OSError`` se o arquivo não existir ou a cópia falhar — o chamador
    mostra o erro, em vez de inserir uma referência quebrada.
    """
    origem = Path(image).resolve()
    if not origem.is_file():
        raise OSError(f"imagem não encontrada: {origem}")

    alt = origem.stem

    if document_path is None:
        # Documento novo, ainda sem onde salvar: não existe caminho relativo.
        log.info("Documento sem arquivo salvo; usando caminho absoluto.")
        return PreparedImage(
            source=origem, url=markdown_url(origem), alt=alt, relative=False
        )

    documento = Path(document_path).resolve()
    pasta = documento.parent

    if is_inside(origem, pasta):
        return PreparedImage(
            source=origem, url=relative_url(origem, pasta), alt=alt
        )

    if not copy_external:
        return PreparedImage(
            source=origem, url=markdown_url(origem), alt=alt, relative=False
        )

    destino = copy_into_document(origem, documento, folder)
    return PreparedImage(
        source=origem,
        url=relative_url(destino, pasta),
        alt=alt,
        copied_to=destino,
    )
