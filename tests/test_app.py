"""Testes do bootstrap do aplicativo.

Cobrem o que só se percebe olhando a interface pronta: a tradução dos diálogos
padrão e a preparação da linha de comando.
"""

from __future__ import annotations

from pathlib import Path

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


def traducao_disponivel(idioma: str) -> bool:
    """Se existe catálogo do Qt para o idioma."""
    pasta = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    return (pasta / f"qtbase_{idioma}.qm").is_file()


class TestTraducao:
    """Os botões padrão vêm do Qt, não do app.

    Sem carregar o catálogo, um diálogo escrito em português aparece com
    "Cancel" e "Yes" no meio. O teste fixa o idioma em vez de usar o do sistema:
    num runner em inglês, "Cancel" é a tradução correta, e o teste não teria
    como distinguir isso de uma falha.
    """

    def test_traduz_para_portugues(self, qapp):
        if not traducao_disponivel("pt_BR"):
            pytest.skip("sem catálogo pt_BR no ambiente")

        assert install_translations(qapp, QLocale("pt_BR")) is True

        botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        try:
            textos = [b.text() for b in botoes.buttons()]
            assert "Cancel" not in textos, textos
            assert any("Cancelar" in t for t in textos), textos
        finally:
            botoes.deleteLater()

    def test_guarda_referencia_do_tradutor(self, qapp):
        """Um QTranslator destruído deixa de traduzir.

        Sem manter a referência viva na aplicação, o objeto sairia de escopo no
        fim da função e a tradução pararia de funcionar sem nenhum erro.
        """
        if not traducao_disponivel("pt_BR"):
            pytest.skip("sem catálogo pt_BR no ambiente")

        install_translations(qapp, QLocale("pt_BR"))
        assert getattr(qapp, "_tradutores", None)

    def test_nome_com_underscore(self, qapp):
        """O Qt nomeia com underscore; o uiLanguages devolve com hífen.

        A primeira versão usava o nome com hífen e o load falhava em silêncio,
        deixando os diálogos em inglês sem nenhum erro.
        """
        if not traducao_disponivel("pt_BR"):
            pytest.skip("sem catálogo pt_BR no ambiente")

        # pt_BR é exatamente o caso que expõe a diferença: o uiLanguages devolve
        # "pt-BR", e o arquivo se chama "qtbase_pt_BR.qm".
        assert install_translations(qapp, QLocale("pt_BR")) is True

    def test_idioma_sem_catalogo_nao_explode(self, qapp):
        """Sem catálogo, o app segue com os textos padrão do Qt."""
        resultado = install_translations(qapp, QLocale("kl_GL"))
        assert resultado is False

    def test_idioma_do_sistema_e_aceito(self, qapp):
        resultado = install_translations(qapp)
        assert resultado in (True, False)
