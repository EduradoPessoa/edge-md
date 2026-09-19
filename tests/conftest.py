"""Configuração compartilhada dos testes.

Duas armadilhas do Qt estão resolvidas aqui, e as duas derrubam a suíte inteira
com um estouro de pilha ou violação de acesso, sem traceback que ajude:

1. **Ordem de importação.** O ``QtWebEngineWidgets`` precisa ser importado antes
   de existir qualquer ``QApplication``. Como o pytest importa todos os módulos
   de teste antes de rodar o primeiro, importá-lo aqui garante a ordem certa
   para a suíte toda, independentemente da ordem dos arquivos.

2. **Uma única ``QApplication``.** O WebEngine se inicializa uma vez, contra a
   primeira instância, e não aceita uma segunda. Com um fixture por módulo, a
   aplicação do primeiro módulo era descartada ao fim dele e o segundo módulo
   criava outra — o processo morria. Aqui ela é de sessão e fica viva até o fim.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Antes de qualquer QApplication, e tolerante à ausência do WebEngine para que
# a parte da suíte que não depende dele continue rodando.
try:  # noqa: SIM105 - o import tem efeito colateral necessário
    from PyQt6 import QtWebEngineWidgets  # noqa: F401

    WEBENGINE_DISPONIVEL = True
except ImportError:  # pragma: no cover - ambiente sem WebEngine
    WEBENGINE_DISPONIVEL = False

from edgemd.render import MarkdownRenderer  # noqa: E402

#: Referência de sessão. Sem ela, a última referência Python à aplicação seria
#: descartada ao fim do primeiro módulo que a usou, destruindo o objeto C++.
_APLICACAO = None


@pytest.fixture(scope="session")
def qapp():
    """A ``QApplication`` da suíte inteira."""
    global _APLICACAO
    from PyQt6.QtWidgets import QApplication

    # sys.argv real: o Chromium lê a linha de comando para se inicializar, e uma
    # lista vazia o impede de subir.
    _APLICACAO = QApplication.instance() or QApplication(sys.argv)
    return _APLICACAO


@pytest.fixture(scope="session")
def renderer() -> MarkdownRenderer:
    """Um renderer por sessão: montar o parser é caro e ele é imutável."""
    return MarkdownRenderer()


# --------------------------------------------------------------------------
# Espera por eventos
# --------------------------------------------------------------------------
# Os testes não usam ``QApplication.exec()``. Com uma aplicação compartilhada
# pela sessão, um ``quit()`` pedido por um teste anterior faz o ``exec()``
# seguinte retornar imediatamente — o teste passaria sozinho e falharia na
# suíte. Bombear eventos não tem esse acoplamento.

def pump(app, ms: int) -> None:
    """Processa eventos por ``ms`` milissegundos."""
    import time

    from PyQt6.QtCore import QCoreApplication, QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        app.processEvents()
        QCoreApplication.sendPostedEvents()
        time.sleep(0.005)


def wait_until(app, predicate, timeout_ms: int = 30_000, step_ms: int = 25) -> bool:
    """Bombeia eventos até ``predicate()`` virar verdadeiro, ou até estourar.

    Devolve o resultado final da condição, então o chamador pode usá-lo num
    ``assert`` e receber uma falha clara em vez de um teste que segue adiante
    com estado pela metade.
    """
    decorrido = 0
    while decorrido < timeout_ms:
        if predicate():
            return True
        pump(app, step_ms)
        decorrido += step_ms
    return predicate()


@pytest.fixture
def md_file(tmp_path: Path):
    """Cria um .md temporário e devolve seu caminho."""

    def create(text: str, name: str = "nota.md", *, encoding: str = "utf-8", eol: str = "\n") -> Path:
        path = tmp_path / name
        payload = text.replace("\n", eol).encode(encoding)
        path.write_bytes(payload)
        return path

    return create
