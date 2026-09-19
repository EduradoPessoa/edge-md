"""Testes do bootstrap do aplicativo.

Cobrem o que só se percebe olhando a interface pronta: a tradução dos diálogos
padrão e a correta preparação da linha de comando.
"""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6 import QtWebEngineWidgets  # noqa: F401,E402  (antes do QApplication)
from PyQt6.QtCore import QLibraryInfo, QLocale  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialogButtonBox  # noqa: E402

from edgemd.app import install_translations, parse_arguments  # noqa: E402


class TestArgumentos:
    def test_arquivos(self):
        args, _ = parse_arguments(["a.md", "b.md"])
        assert args.files == ["a.md", "b.md"]

    def test_sem_argumentos(self):
        args, _ = parse_arguments([])
        assert args.files == []

    def test_opcoes(self):
        args, _ = parse_arguments(["--hidden", "--new", "nota.md"])
        assert args.hidden is True
        assert args.new is True
        assert args.files == ["nota.md"]

    def test_argumento_desconhecido_e_ignorado(self):
        """O Windows injeta argumentos próprios em chamadas COM."""
        args, unknown = parse_arguments(["-Embedding", "nota.md"])
        assert args.files == ["nota.md"]
        assert "-Embedding" in unknown

    def test_no_session(self):
        args, _ = parse_arguments(["--no-session"])
        assert args.no_session is True


class TestTraducao:
    @pytest.fixture(autouse=True)
    def limpar(self):
        yield

    def test_carrega_o_catalogo(self, qapp):
        """Os botões padrão vêm do Qt, não do app.

        Sem carregar o catálogo, um diálogo em português aparece com "Cancel" e
        "Yes" no meio — foi o que aconteceu antes desta função existir.
        """
        disponivel = (
            QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
            and QLocale.system().name()
        )
        if not disponivel:
            pytest.skip("sem catálogo de tradução no ambiente")

        resultado = install_translations(qapp)
        if not resultado:
            pytest.skip("sem tradução para o idioma do sistema")

        botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        try:
            textos = [b.text() for b in botoes.buttons()]
            # Não basta "não é inglês": o teste precisa provar que traduziu.
            assert "Cancel" not in textos, textos
        finally:
            botoes.deleteLater()

    def test_guarda_referencia_do_tradutor(self, qapp):
        """Um QTranslator destruído deixa de traduzir.

        Sem a referência viva na aplicação, o objeto sairia de escopo no fim da
        função e a tradução pararia de funcionar sem nenhum erro.
        """
        if not install_translations(qapp):
            pytest.skip("sem tradução para o idioma do sistema")
        assert getattr(qapp, "_tradutores", None)

    def test_nome_com_underscore(self, qapp):
        """O Qt nomeia com underscore; o uiLanguages devolve com hífen.

        A primeira versão usava o nome com hífen e o load falhava em silêncio.
        """
        from pathlib import Path

        pasta = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
        if not pasta.is_dir():
            pytest.skip("sem pasta de traduções")

        # Se existe o arquivo para o idioma do sistema, a função precisa achá-lo.
        idioma = QLocale.system().name()
        esperado = pasta / f"qtbase_{idioma}.qm"
        if not esperado.is_file():
            pytest.skip(f"sem catálogo para {idioma}")

        assert install_translations(qapp) is True
