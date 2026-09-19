"""Rede de segurança para falhas inesperadas na interface.

Motivo desta existir, medido nesta máquina: no PyQt6, uma exceção não tratada
dentro de um slot **não** vira uma mensagem de erro — ela interrompe a entrega
de eventos. Os temporizadores seguintes deixam de disparar, o app para de
responder e o usuário só vê "o programa fechou sozinho". Foi exatamente o que
aconteceu na exportação para PDF, onde um ``NameError`` (uma variável que ficou
para trás numa refatoração) derrubou o aplicativo inteiro.

São duas camadas, com papéis diferentes:

* :func:`install_exception_hook` é a rede global. Pega qualquer exceção que
  escape, registra no log e mostra um aviso — o app continua rodando.
* :func:`guarded_slot` protege um slot específico, com uma mensagem que explica
  o que o usuário tentava fazer.

A camada global sozinha já evita a morte silenciosa; a segunda existe porque
"falha ao exportar o PDF" é mais útil do que "erro inesperado".
"""

from __future__ import annotations

import functools
import inspect
import logging
import sys
import traceback
from typing import Any, Callable

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox, QWidget

log = logging.getLogger(__name__)

#: Quantas vezes o aviso global pode aparecer antes de silenciar. Sem isso, um
#: erro que se repete a cada tela pintada encheria a tela de diálogos.
MAX_GLOBAL_DIALOGS = 3

_shown = 0


def _accepted_positional(func: Callable) -> int:
    """Quantos argumentos posicionais ``func`` aceita, fora o ``self``.

    Sinais do Qt passam argumentos que o slot pode não querer — o
    ``QAction.triggered`` manda um ``bool`` com o estado de "marcado", e o
    ``QTimer.timeout`` não manda nada. Repassar tudo cegamente quebra o slot:
    foi assim que a exportação para PDF deixou de funcionar pelo menu, com
    ``takes 1 positional argument but 2 were given``.
    """
    try:
        parameters = inspect.signature(func).parameters.values()
    except (TypeError, ValueError):  # pragma: no cover - callable exótico
        return 0

    total = 0
    for parameter in parameters:
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            total += 1
        elif parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            # Aceita qualquer quantidade: repassamos tudo.
            return -1
    # O primeiro parâmetro é o self, que já é passado explicitamente.
    return max(0, total - 1)


def guarded_slot(title: str, message: str = "") -> Callable:
    """Protege um slot de interface: falha vira aviso, não morte do app.

    ``title`` é o cabeçalho do diálogo e ``message`` a explicação do que se
    tentava fazer. A exceção original entra no diálogo e no log, para que o
    problema continue diagnosticável.

    Os argumentos extras que o sinal mandar são filtrados conforme a função
    aceita, então o decorador pode ser usado em qualquer slot — ligado a uma
    ação de menu, a um temporizador ou chamado direto.
    """

    def decorator(func: Callable) -> Callable:
        aceitos = _accepted_positional(func)

        @functools.wraps(func)
        def wrapper(self, *args: Any, **kwargs: Any) -> Any:
            if aceitos >= 0:
                args = args[:aceitos]
            try:
                return func(self, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - é o ponto da proteção
                log.exception("Falha em %s", func.__qualname__)
                parent = self if isinstance(self, QWidget) else None
                detail = f"{message}\n\n" if message else ""
                QMessageBox.critical(
                    parent,
                    title,
                    f"{detail}Ocorreu um erro inesperado:\n\n"
                    f"{type(exc).__name__}: {exc}\n\n"
                    "O aplicativo continua aberto. Os detalhes foram "
                    "registrados em edgemd.log.",
                )
                return None

        return wrapper

    return decorator


def install_exception_hook(app: Any = None) -> None:
    """Instala o tratador global de exceções não capturadas.

    Sem isto, uma exceção fora de um ``try`` interrompe o laço de eventos e o
    app morre sem explicação — nem no console, já que ele roda por ``pythonw``.
    """

    def hook(exc_type: type[BaseException], value: BaseException, tb: Any) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            # Ctrl+C continua sendo Ctrl+C.
            sys.__excepthook__(exc_type, value, tb)
            return

        log.critical(
            "Exceção não tratada:\n%s",
            "".join(traceback.format_exception(exc_type, value, tb)),
        )

        global _shown
        if _shown >= MAX_GLOBAL_DIALOGS:
            return
        _shown += 1

        def mostrar() -> None:
            try:
                QMessageBox.critical(
                    None,
                    "Erro inesperado",
                    f"Ocorreu um erro inesperado:\n\n{exc_type.__name__}: {value}\n\n"
                    "O aplicativo continua aberto. Os detalhes foram "
                    "registrados em edgemd.log.",
                )
            except Exception:  # noqa: BLE001 - o aviso nunca pode derrubar nada
                log.exception("Falha ao mostrar o aviso de erro.")

        # Adia o diálogo para depois que a pilha atual desenrolar: abrir uma
        # janela modal de dentro do tratador de exceção é pedir encrenca.
        QTimer.singleShot(0, mostrar)

    sys.excepthook = hook
    log.debug("Tratador global de exceções instalado.")


def reset_dialog_budget() -> None:
    """Restaura o limite de avisos globais. Usado pelos testes."""
    global _shown
    _shown = 0
