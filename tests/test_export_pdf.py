"""Testes da exportação para PDF.

Este arquivo existe por causa de um defeito real: a exportação para PDF
levantava ``NameError`` (uma variável ``html`` que sobreviveu a uma
refatoração) e **derrubava o aplicativo**. O teste de ponta a ponta abaixo é o
que impede a volta desse defeito.

Precisa de Qt WebEngine e de um laço de eventos de verdade, então é mais lento
que o resto da suíte — a troca vale, porque é o único caminho que exercita a
impressão real do Chromium.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtWebEngineCore")

from PyQt6 import QtWebEngineWidgets  # noqa: F401,E402  (antes do QApplication)
from PyQt6.QtCore import QCoreApplication, QEvent, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from edgemd.export import PdfExporter  # noqa: E402
from edgemd.render import MarkdownRenderer  # noqa: E402

#: O PDF leva alguns segundos: o Chromium carrega, espera o Mermaid/KaTeX e
#: então imprime.
PDF_TIMEOUT_MS = 30000


def destruir(widget, app: QApplication) -> None:
    """Destrói um widget e força a exclusão das suas páginas do WebEngine.

    ``deleteLater`` só agenda; o Qt processa exclusões adiadas quando o laço
    volta ao nível principal, o que não acontece num teardown de teste. Sem
    forçar aqui, o ``QWebEngineProfile`` é liberado antes das páginas e o Qt
    avisa "WebEnginePage still not deleted" — poluindo a saída da suíte, que é
    justamente onde avisos de verdade precisam aparecer.

    No app real isso não é necessário: o laço de eventos roda até o fim e
    processa as exclusões sozinho (verificado).
    """
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture(scope="module")
def qapp():
    # Precisa de sys.argv real: o Chromium usa a linha de comando para se
    # inicializar, e uma lista vazia faz o WebEngine não subir.
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture(scope="module")
def renderer() -> MarkdownRenderer:
    return MarkdownRenderer()


def exportar(qapp, renderer, texto: str, origem: Path, destino: Path, **kwargs) -> tuple[str, bool]:
    """Roda uma exportação até o fim e devolve ``(caminho, sucesso)``."""
    resultado: dict[str, object] = {}

    exporter = PdfExporter()
    exporter._em_uso = True  # mantém a referência viva durante o teste

    def ao_terminar(caminho: str, ok: bool) -> None:
        resultado["caminho"] = caminho
        resultado["ok"] = ok
        QTimer.singleShot(0, qapp.quit)

    exporter.finished.connect(ao_terminar)
    exporter.export(renderer, texto, origem, destino, **kwargs)

    QTimer.singleShot(PDF_TIMEOUT_MS, qapp.quit)
    qapp.exec()

    assert "ok" in resultado, f"a exportação não terminou em {PDF_TIMEOUT_MS} ms"
    return str(resultado["caminho"]), bool(resultado["ok"])


class TestExportacaoPdf:
    def test_gera_pdf(self, qapp, renderer, tmp_path):
        origem = tmp_path / "nota.md"
        origem.write_text("# Título\n\nUm parágrafo qualquer.\n", encoding="utf-8")
        destino = tmp_path / "saida.pdf"

        caminho, ok = exportar(
            qapp, renderer, origem.read_text(encoding="utf-8"), origem, destino
        )

        assert ok is True
        assert Path(caminho) == destino.resolve()
        assert destino.is_file()

        # Um PDF válido começa com %PDF- e tem tamanho de documento de verdade.
        conteudo = destino.read_bytes()
        assert conteudo.startswith(b"%PDF-")
        assert len(conteudo) > 1000

    def test_nao_levanta_excecao_com_conteudo_rico(self, qapp, renderer, tmp_path):
        """Regressão: o conteúdo rico é o que fazia o app morrer."""
        texto = (
            "# Documento\n\n"
            "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
            "```python\nx = 1\n```\n\n"
            "```mermaid\ngraph TD\n  A-->B\n```\n\n"
            "Fórmula: $E = mc^2$\n"
        )
        origem = tmp_path / "rico.md"
        origem.write_text(texto, encoding="utf-8")
        destino = tmp_path / "rico.pdf"

        caminho, ok = exportar(qapp, renderer, texto, origem, destino)

        assert ok is True
        assert Path(caminho).stat().st_size > 1000

    @pytest.mark.parametrize("tema", ["light", "dark"])
    def test_temas(self, qapp, renderer, tmp_path, tema):
        origem = tmp_path / "n.md"
        origem.write_text("# T\n", encoding="utf-8")
        destino = tmp_path / f"{tema}.pdf"

        _, ok = exportar(qapp, renderer, "# T\n", origem, destino, theme=tema)
        assert ok is True

    def test_destino_invalido_nao_derruba_o_app(self, qapp, renderer, tmp_path):
        """Pasta inexistente: o Chromium não consegue gravar.

        O importante é o app sobreviver e o sinal de conclusão chegar mesmo
        assim — a falha precisa virar aviso, não silêncio.
        """
        origem = tmp_path / "n.md"
        origem.write_text("# T\n", encoding="utf-8")
        destino = tmp_path / "nao" / "existe" / "saida.pdf"

        _, ok = exportar(qapp, renderer, "# T\n", origem, destino)
        assert ok is False

    def test_sem_caminho_de_origem(self, qapp, renderer, tmp_path):
        """Documento novo, ainda sem arquivo salvo."""
        destino = tmp_path / "novo.pdf"
        _, ok = exportar(qapp, renderer, "# Sem arquivo\n", None, destino)
        assert ok is True
        assert destino.is_file()


class TestExportacaoPelaJanela:
    """Reproduz o caminho exato do usuário: menu → Exportar PDF.

    O defeito original vivia aqui, no fluxo da janela: o slot chamava o
    exportador e a exceção resultante matava o aplicativo em vez de mostrar um
    aviso. Estes testes passam pela janela de verdade.
    """

    def test_exporta_pdf_pelo_menu(self, qapp, tmp_path, monkeypatch):
        """Aciona a ação de verdade, e não só chama o método.

        O teste original chamava ``janela.export_current_pdf()`` direto e por
        isso não viu que o ``QAction.triggered`` manda um ``bool`` que o slot
        não aceitava: a exportação **pelo menu** estava quebrada e o teste
        passava. Sempre que um slot é ligado a um sinal, o teste tem de passar
        pelo sinal.
        """
        from PyQt6.QtWidgets import QFileDialog, QMessageBox

        from edgemd.config import AppConfig
        from edgemd.render import MarkdownRenderer
        from edgemd.window import MainWindow

        origem = tmp_path / "nota.md"
        origem.write_text("# Título\n\nTexto.\n", encoding="utf-8")
        destino = tmp_path / "saida.pdf"

        # O diálogo de salvar é substituído: o teste não pode abrir janela modal.
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: (str(destino), "")),
        )
        erros: list[tuple] = []
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            staticmethod(lambda *a, **k: erros.append(a)),
        )

        janela = MainWindow(
            AppConfig(settings_path=tmp_path / "cfg.ini"), MarkdownRenderer()
        )
        try:
            janela.open_paths([str(origem)])
            assert janela.current_tab is not None

            janela.action_export_pdf.trigger()

            # O exportador fica em _pdf_exporter até o sinal de conclusão.
            for _ in range(60):
                if janela._pdf_exporter is None:
                    break
                QTimer.singleShot(250, qapp.quit)
                qapp.exec()

            assert janela._pdf_exporter is None, "a exportação não terminou"
            assert erros == [], f"apareceu um erro na exportação: {erros}"
            assert destino.is_file(), "o PDF não foi gerado"
            assert destino.read_bytes().startswith(b"%PDF-")
        finally:
            janela._force_close = True
            janela.close()
            destruir(janela, qapp)

    def test_exporta_html_pelo_menu(self, qapp, tmp_path, monkeypatch):
        """Mesmo cuidado para o HTML: acionado pelo sinal, não pelo método."""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox

        from edgemd.config import AppConfig
        from edgemd.render import MarkdownRenderer
        from edgemd.window import MainWindow

        origem = tmp_path / "nota.md"
        origem.write_text("# Título\n\nTexto com **ênfase**.\n", encoding="utf-8")
        destino = tmp_path / "saida.html"

        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: (str(destino), "")),
        )
        erros: list[tuple] = []
        monkeypatch.setattr(
            QMessageBox, "critical", staticmethod(lambda *a, **k: erros.append(a))
        )

        janela = MainWindow(
            AppConfig(settings_path=tmp_path / "cfg.ini"), MarkdownRenderer()
        )
        try:
            janela.open_paths([str(origem)])
            janela.action_export_html.trigger()

            assert erros == [], f"apareceu um erro na exportação: {erros}"
            assert destino.is_file()
            assert destino.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
        finally:
            janela._force_close = True
            janela.close()
            destruir(janela, qapp)

    def test_exportacao_ja_em_andamento_e_recusada(self, qapp, tmp_path, monkeypatch):
        """Dois cliques seguidos não podem disputar o mesmo arquivo."""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox

        from edgemd.config import AppConfig
        from edgemd.render import MarkdownRenderer
        from edgemd.window import MainWindow

        origem = tmp_path / "nota.md"
        origem.write_text("# T\n", encoding="utf-8")
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: (str(tmp_path / "s.pdf"), "")),
        )
        avisos: list[tuple] = []
        monkeypatch.setattr(
            QMessageBox, "information", staticmethod(lambda *a, **k: avisos.append(a))
        )

        janela = MainWindow(
            AppConfig(settings_path=tmp_path / "cfg.ini"), MarkdownRenderer()
        )
        try:
            janela.open_paths([str(origem)])
            # Simula uma exportação em andamento.
            janela._pdf_exporter = object()

            janela.export_current_pdf()
            assert avisos, "a segunda exportação deveria ter sido recusada"
        finally:
            janela._pdf_exporter = None
            janela._force_close = True
            janela.close()
            destruir(janela, qapp)
