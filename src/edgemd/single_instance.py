"""Instância única do aplicativo, com passagem de arquivos entre processos.

O problema que isto resolve: o usuário tem o app na bandeja e dá clique duplo
em cinco arquivos .md no Explorer. Sem controle, o Windows sobe cinco processos
e cinco janelas. Com isto, o primeiro vira a instância primária e os outros
quatro entregam o caminho do arquivo para ela e encerram.

O transporte é ``QLocalServer``/``QLocalSocket`` — no Windows isso é um named
pipe. Duas armadilhas tratadas aqui:

* **Socket órfão.** Se o processo anterior morreu sem fechar (crash, kill no
  Gerenciador de Tarefas), o nome continua registrado e ``listen()`` falha com
  ``AddressInUseError``. Por isso tentamos remover o servidor antes de escutar,
  e só então desistimos e assumimos que há outra instância viva.
* **Mensagem partida.** O pipe não preserva fronteiras de mensagem, então cada
  mensagem é uma linha JSON terminada em ``\\n`` e o leitor acumula até achar a
  quebra.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger(__name__)

#: Tempo máximo esperando a instância primária responder.
CONNECT_TIMEOUT_MS = 1200
#: Tempo máximo esperando o cliente enviar sua mensagem.
READ_TIMEOUT_MS = 1500


class SingleInstance(QObject):
    """Garante uma única instância e entrega mensagens a ela."""

    #: Emitido na instância primária quando outra pede para abrir arquivos.
    messageReceived = pyqtSignal(dict)

    def __init__(self, key: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._key = key
        self._server: QLocalServer | None = None
        self._buffers: dict[QLocalSocket, bytearray] = {}

    # ------------------------------------------------------------------
    # Lado da instância primária
    # ------------------------------------------------------------------
    def try_become_primary(self) -> bool:
        """Tenta assumir o papel de instância primária.

        Devolve False quando já existe outra instância atendendo — nesse caso
        o chamador deve entregar seus argumentos via :meth:`send` e sair.
        """
        if self._probe_existing():
            return False

        # removeServer limpa o nome de um servidor que morreu sem fechar.
        # Se ainda houver um servidor vivo, o probe acima já teria retornado.
        QLocalServer.removeServer(self._key)

        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(self._key):
            log.error("Não foi possível escutar em '%s': %s", self._key, server.errorString())
            return False

        server.newConnection.connect(self._on_new_connection)
        self._server = server
        log.info("Instância primária ativa (canal '%s').", self._key)
        return True

    def _probe_existing(self) -> bool:
        """True se outra instância está viva e aceitando conexões.

        Só testa a conexão, sem enviar nada. O estado é checado antes do
        ``waitForDisconnected`` porque ele avisa (no stderr) quando chamado
        com o socket já desconectado.
        """
        socket = QLocalSocket()
        socket.connectToServer(self._key)
        if not socket.waitForConnected(200):
            return False
        socket.disconnectFromServer()
        if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            socket.waitForDisconnected(200)
        return True

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda s=socket: self._on_ready_read(s))
            socket.disconnected.connect(lambda s=socket: self._cleanup(s))
            socket.errorOccurred.connect(lambda _err, s=socket: self._cleanup(s))

    def _on_ready_read(self, socket: QLocalSocket) -> None:
        buffer = self._buffers.get(socket)
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))

        while b"\n" in buffer:
            raw, _, rest = buffer.partition(b"\n")
            buffer.clear()
            buffer.extend(rest)
            self._dispatch(raw)

    def _dispatch(self, raw: bytes) -> None:
        if not raw.strip():
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("Mensagem IPC inválida descartada: %r", raw[:200])
            return
        if isinstance(payload, dict):
            log.debug("IPC recebido: %s", payload)
            self.messageReceived.emit(payload)

    def _cleanup(self, socket: QLocalSocket) -> None:
        self._buffers.pop(socket, None)
        socket.deleteLater()

    # ------------------------------------------------------------------
    # Lado do processo secundário
    # ------------------------------------------------------------------
    def send(self, payload: dict[str, Any]) -> bool:
        """Entrega uma mensagem à instância primária.

        Devolve False se ninguém atendeu — o chamador então deve assumir o
        papel de primária em vez de simplesmente sair sem abrir nada.

        O laço de espera depois do ``write`` não é excesso de zelo. No Windows
        o ``QLocalSocket`` grava no pipe de forma assíncrona: ``write``+
        ``flush`` apenas enfileiram os bytes, e o ``WriteFile`` real acontece
        depois, no laço de eventos. Chamar ``disconnectFromServer`` nesse
        intervalo **descarta os dados em silêncio** — o processo secundário sai
        reportando sucesso e o arquivo nunca abre na instância viva.

        Medido nesta máquina: desconectar logo após o ``flush`` falha 100% das
        vezes; bombear o laço até ``bytesToWrite()`` zerar funciona. Por isso a
        espera é por ``bytesToWrite()``, e não por ``waitForBytesWritten``, que
        retorna False quando não há nada pendente no momento da chamada e daria
        uma falsa sensação de conclusão.
        """
        socket = QLocalSocket()
        socket.connectToServer(self._key)
        if not socket.waitForConnected(CONNECT_TIMEOUT_MS):
            log.info("Nenhuma instância primária respondeu em '%s'.", self._key)
            return False

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
        socket.write(data)
        socket.flush()

        deadline = time.monotonic() + READ_TIMEOUT_MS / 1000
        application = QCoreApplication.instance()
        while socket.bytesToWrite() > 0 and time.monotonic() < deadline:
            socket.waitForBytesWritten(50)
            if application is not None:
                # Deixa o escritor de pipe progredir; sem isto o laço apenas
                # gira sem que os bytes saiam.
                application.processEvents()

        pendente = socket.bytesToWrite()
        if pendente > 0:
            log.warning("%d byte(s) não entregues ao canal IPC.", pendente)

        socket.disconnectFromServer()
        if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            socket.waitForDisconnected(READ_TIMEOUT_MS)
        return True

    # ------------------------------------------------------------------
    def close(self) -> None:
        """Libera o canal para que a próxima execução seja primária."""
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(self._key)
            self._server = None
