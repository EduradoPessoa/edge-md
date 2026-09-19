"""Testes do canal de instância única.

O caso que importa: clique duplo em vários .md no Explorer não pode gerar
várias janelas. E se o canal estiver morto (processo anterior travou), o novo
processo precisa assumir como primário em vez de sair sem abrir nada.
"""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("PyQt6.QtNetwork")

from PyQt6.QtCore import QCoreApplication  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from edgemd.single_instance import SingleInstance  # noqa: E402




@pytest.fixture
def key() -> str:
    """Chave única por teste, para não colidir com o app em execução."""
    return f"edgemd-test-{uuid.uuid4().hex}"


def pump(app, ms: int = 400) -> None:
    """Roda o laço de eventos por um tempo, para o IPC assentar.

    O QLocalSocket é assíncrono; sem bombear eventos o sinal nunca chega. O
    sleep evita girar em falso consumindo CPU enquanto o pipe transfere.
    """
    import time

    from PyQt6.QtCore import QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        app.processEvents()
        QCoreApplication.sendPostedEvents()
        time.sleep(0.005)


class TestPrimaria:
    def test_primeiro_vira_primario(self, qapp, key):
        instancia = SingleInstance(key)
        assert instancia.try_become_primary() is True
        instancia.close()

    def test_segundo_nao_vira_primario(self, qapp, key):
        primaria = SingleInstance(key)
        assert primaria.try_become_primary() is True

        secundaria = SingleInstance(key)
        assert secundaria.try_become_primary() is False

        primaria.close()

    def test_close_libera_o_canal(self, qapp, key):
        primeira = SingleInstance(key)
        assert primeira.try_become_primary() is True
        primeira.close()

        # Depois de fechar, a próxima execução precisa conseguir assumir.
        segunda = SingleInstance(key)
        assert segunda.try_become_primary() is True
        segunda.close()

    def test_socket_orfao_nao_bloqueia(self, qapp, key):
        """Simula um processo que morreu sem fechar o servidor.

        Um cliente conectado e descartado deixa o nome registrado; a próxima
        execução precisa conseguir assumir mesmo assim.
        """
        from PyQt6.QtNetwork import QLocalSocket

        orfao = QLocalSocket()
        orfao.connectToServer(key)
        orfao.waitForConnected(200)
        del orfao

        instancia = SingleInstance(key)
        assert instancia.try_become_primary() is True
        instancia.close()


class TestMensagens:
    def test_entrega_payload(self, qapp, key):
        primaria = SingleInstance(key)
        assert primaria.try_become_primary() is True

        recebidas: list[dict] = []
        primaria.messageReceived.connect(recebidas.append)

        secundaria = SingleInstance(key)
        enviado = secundaria.send({"action": "open", "paths": [r"C:\notas\a.md"]})
        assert enviado is True

        pump(qapp, 600)
        primaria.close()

        assert len(recebidas) == 1
        assert recebidas[0]["action"] == "open"
        assert recebidas[0]["paths"] == [r"C:\notas\a.md"]

    def test_preserva_acentuacao(self, qapp, key):
        primaria = SingleInstance(key)
        primaria.try_become_primary()

        recebidas: list[dict] = []
        primaria.messageReceived.connect(recebidas.append)

        caminho = r"C:\Users\josé\Notas\Ação e coração.md"
        SingleInstance(key).send({"action": "open", "paths": [caminho]})
        pump(qapp, 600)
        primaria.close()

        assert recebidas and recebidas[0]["paths"] == [caminho]

    def test_varias_mensagens_seguidas(self, qapp, key):
        primaria = SingleInstance(key)
        primaria.try_become_primary()

        recebidas: list[dict] = []
        primaria.messageReceived.connect(recebidas.append)

        for index in range(4):
            SingleInstance(key).send({"action": "open", "paths": [f"n{index}.md"]})
            pump(qapp, 120)

        pump(qapp, 400)
        primaria.close()

        assert len(recebidas) == 4
        assert [r["paths"][0] for r in recebidas] == [f"n{i}.md" for i in range(4)]

    def test_send_sem_primaria_devolve_false(self, qapp, key):
        # Ninguém escutando: o chamador deve poder detectar e assumir.
        assert SingleInstance(key).send({"action": "open", "paths": []}) is False

    def test_payload_invalido_e_ignorado(self, qapp, key):
        """Lixo no canal não pode derrubar a instância primária."""
        from PyQt6.QtNetwork import QLocalSocket

        primaria = SingleInstance(key)
        primaria.try_become_primary()

        recebidas: list[dict] = []
        primaria.messageReceived.connect(recebidas.append)

        socket = QLocalSocket()
        socket.connectToServer(key)
        assert socket.waitForConnected(500)
        socket.write(b"isto nao e json\n")
        socket.flush()
        socket.waitForBytesWritten(500)

        pump(qapp, 500)
        socket.disconnectFromServer()
        primaria.close()

        assert recebidas == []
