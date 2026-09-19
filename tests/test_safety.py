"""Testes da rede de segurança da interface.

Estes testes existem por causa de um defeito concreto: um ``NameError`` dentro
do slot de exportação para PDF derrubou o aplicativo inteiro. No PyQt6 uma
exceção não tratada num slot interrompe a entrega de eventos — o app para de
responder e o usuário só percebe que "fechou sozinho".
"""

from __future__ import annotations

import logging
import sys

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

from edgemd.safety import (  # noqa: E402
    MAX_GLOBAL_DIALOGS,
    guarded_slot,
    install_exception_hook,
    reset_dialog_budget,
)




@pytest.fixture
def sem_dialogos(monkeypatch):
    """Impede que os testes abram caixas de diálogo modais.

    Sem isto, um teste que verifica o caminho de erro ficaria travado esperando
    alguém clicar em OK.
    """
    capturados: list[tuple[str, str]] = []

    def fake_critical(parent, title, text, *args, **kwargs):
        capturados.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(fake_critical))
    return capturados


class Alvo(QWidget):
    """Objeto com slots protegidos, para exercitar o decorador."""

    def __init__(self) -> None:
        super().__init__()
        self.chamou = False

    @guarded_slot("Falhou", "Não foi possível fazer a coisa.")
    def slot_ok(self) -> str:
        self.chamou = True
        return "resultado"

    @guarded_slot("Falhou", "Não foi possível fazer a coisa.")
    def slot_que_falha(self) -> None:
        raise ValueError("erro proposital")


class TestGuardedSlot:
    def test_repassa_o_retorno(self, qapp, sem_dialogos):
        alvo = Alvo()
        assert alvo.slot_ok() == "resultado"
        assert alvo.chamou is True

    def test_nao_propaga_a_excecao(self, qapp, sem_dialogos):
        """O ponto central: a exceção morre aqui, não no laço de eventos."""
        alvo = Alvo()
        assert alvo.slot_que_falha() is None

    def test_avisa_o_usuario(self, qapp, sem_dialogos):
        Alvo().slot_que_falha()
        assert len(sem_dialogos) == 1
        titulo, texto = sem_dialogos[0]
        assert "Falhou" in titulo
        # A mensagem precisa dizer o que se tentava fazer e qual foi o erro.
        assert "Não foi possível fazer a coisa" in texto
        assert "erro proposital" in texto
        assert "continua aberto" in texto

    def test_registra_no_log(self, qapp, sem_dialogos, caplog):
        with caplog.at_level(logging.ERROR):
            Alvo().slot_que_falha()
        assert any("erro proposital" in r.getMessage() or r.exc_info for r in caplog.records)

    def test_preserva_o_nome_da_funcao(self):
        assert Alvo.slot_que_falha.__name__ == "slot_que_falha"


class TestArgumentosDeSinal:
    """Sinais do Qt mandam argumentos que o slot pode não querer.

    Esta classe existe por causa de um defeito real: o ``QAction.triggered``
    manda um ``bool`` com o estado de "marcado". O wrapper do ``guarded_slot``
    repassava tudo, e a exportação para PDF **pelo menu** parou de funcionar com
    ``takes 1 positional argument but 2 were given``. O teste que existia
    chamava o método direto, sem passar pelo sinal, então não via nada.
    """

    def test_slot_sem_parametros_ignora_o_bool(self, qapp, sem_dialogos):
        from PyQt6.QtGui import QAction

        chamadas: list = []

        class Janela(QWidget):
            @guarded_slot("Falhou")
            def sem_args(self) -> str:
                chamadas.append("sem_args")
                return "ok"

        janela = Janela()
        acao = QAction("x", janela)
        acao.triggered.connect(janela.sem_args)

        acao.trigger()  # o sinal manda o bool 'checked'
        assert chamadas == ["sem_args"]

    def test_slot_que_aceita_bool_recebe(self, qapp, sem_dialogos):
        from PyQt6.QtGui import QAction

        recebidos: list = []

        class Janela(QWidget):
            @guarded_slot("Falhou")
            def com_bool(self, marcado: bool = False) -> None:
                recebidos.append(marcado)

        janela = Janela()
        acao = QAction("x", janela)
        acao.setCheckable(True)
        acao.triggered.connect(janela.com_bool)

        acao.trigger()
        assert recebidos == [True]

    def test_slot_com_dois_argumentos(self, qapp, sem_dialogos):
        """Sinais como o de conclusão do PDF mandam dois valores."""
        recebidos: list = []

        class Alvo2(QWidget):
            @guarded_slot("Falhou")
            def dois(self, caminho: str, ok: bool) -> None:
                recebidos.append((caminho, ok))

        alvo = Alvo2()
        alvo.dois("a.pdf", True)
        assert recebidos == [("a.pdf", True)]

    def test_contagem_de_argumentos(self):
        from edgemd.safety import _accepted_positional

        def sem_extra(self) -> None: ...
        def um_extra(self, valor: bool) -> None: ...
        def dois_extras(self, a: str, b: bool) -> None: ...
        def varargs(self, *args) -> None: ...

        assert _accepted_positional(sem_extra) == 0
        assert _accepted_positional(um_extra) == 1
        assert _accepted_positional(dois_extras) == 2
        assert _accepted_positional(varargs) == -1


class TestExceptionHook:
    def test_instala(self, qapp):
        original = sys.excepthook
        try:
            install_exception_hook(qapp)
            assert sys.excepthook is not original
        finally:
            sys.excepthook = original

    def test_excecao_nao_mata_o_laco(self, qapp, sem_dialogos):
        """O comportamento que motivou tudo isto.

        Com o tratador instalado, o temporizador seguinte continua disparando —
        é a diferença entre "mostrou um erro" e "o programa sumiu".
        """
        original = sys.excepthook
        reset_dialog_budget()
        try:
            install_exception_hook(qapp)
        except Exception:
            sys.excepthook = original
            raise

        try:
            eventos: list[str] = []

            def primeiro() -> None:
                # Simula o que o PyQt faz: entrega a exceção ao tratador.
                try:
                    raise RuntimeError("falha simulada num slot")
                except RuntimeError:
                    sys.excepthook(*sys.exc_info())

            def segundo() -> None:
                eventos.append("segundo disparou")

            QTimer.singleShot(0, primeiro)
            QTimer.singleShot(120, segundo)

            # Bombear eventos em vez de chamar exec(): a aplicação é
            # compartilhada pela sessão, e um quit() pedido por outro teste faria
            # o exec() retornar antes de o segundo temporizador disparar. Era
            # exatamente isso que fazia este teste passar sozinho e falhar na
            # suíte completa.
            from conftest import pump

            pump(qapp, 600)
        finally:
            sys.excepthook = original

        assert eventos == ["segundo disparou"]

    def test_keyboard_interrupt_passa_direto(self, qapp):
        original = sys.excepthook
        try:
            install_exception_hook(qapp)
            # Não deve levantar nem entrar no ramo de diálogo.
            sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        finally:
            sys.excepthook = original

    def test_limite_de_dialogos(self, qapp, monkeypatch):
        """Um erro repetitivo não pode encher a tela de avisos."""
        original = sys.excepthook
        reset_dialog_budget()
        agendados: list = []

        monkeypatch.setattr(
            QTimer, "singleShot", staticmethod(lambda ms, fn: agendados.append(fn))
        )
        try:
            install_exception_hook(qapp)
            for _ in range(MAX_GLOBAL_DIALOGS + 5):
                sys.excepthook(ValueError, ValueError("repetido"), None)
        finally:
            sys.excepthook = original
            reset_dialog_budget()

        assert len(agendados) == MAX_GLOBAL_DIALOGS
