"""Testes de uma aba de documento.

O que mais importa aqui é a gravação: um editor que corrompe o arquivo do
usuário, ou que troca o encoding sem avisar, é pior do que não existir. Os
testes verificam os bytes no disco, não só o texto em memória.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgemd.editor_tab import EditorTab
from edgemd.render import detect_eol

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    """QApplication viva durante o módulo: criar QWidget sem ela é erro fatal."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def tab(qapp, tmp_path):
    """Fábrica de abas, garantindo limpeza depois do teste."""

    created: list[EditorTab] = []

    def make(path: str | Path | None = None) -> EditorTab:
        widget = EditorTab(path, theme="dark")
        created.append(widget)
        return widget

    yield make

    for widget in created:
        widget.deleteLater()


class TestCriacao:
    def test_novo_documento_sem_arquivo(self, tab):
        documento = tab()
        assert documento.path is None
        assert documento.is_dirty is False
        assert documento.display_name == "Sem título"

    def test_carrega_arquivo(self, tab, tmp_path):
        path = tmp_path / "nota.md"
        path.write_text("# Olá\n", encoding="utf-8")
        documento = tab(path)
        assert documento.path == path.resolve()
        assert documento.editor.toPlainText() == "# Olá\n"
        assert documento.is_dirty is False

    def test_arquivo_inexistente_nao_explode(self, tab, tmp_path):
        documento = tab(tmp_path / "sumiu.md")
        assert documento.path is None
        assert documento.is_dirty is False

    def test_nome_de_aba_com_marcador(self, tab, tmp_path):
        path = tmp_path / "nota.md"
        path.write_text("x", encoding="utf-8")
        documento = tab(path)
        assert documento.display_name == "nota.md"
        documento.editor.insertPlainText("alteração")
        assert documento.is_dirty is True
        assert documento.display_name.endswith("•")


class TestEstadoSujo:
    def test_marcar_e_limpar(self, tab, tmp_path):
        path = tmp_path / "n.md"
        path.write_text("inicial", encoding="utf-8")
        documento = tab(path)

        mudancas: list[bool] = []
        documento.dirtyChanged.connect(mudancas.append)

        documento.editor.insertPlainText("x")
        assert documento.is_dirty is True

        assert documento.save() is True
        assert documento.is_dirty is False
        assert mudancas == [True, False]

    def test_carregar_nao_marca_sujo(self, tab, tmp_path):
        path = tmp_path / "n.md"
        path.write_text("conteúdo", encoding="utf-8")
        documento = tab(path)
        assert documento.is_dirty is False


class TestSalvamento:
    def test_grava_no_disco(self, tab, tmp_path):
        path = tmp_path / "n.md"
        path.write_text("antes", encoding="utf-8")
        documento = tab(path)
        documento.editor.setPlainText("depois")
        assert documento.save() is True
        assert path.read_text(encoding="utf-8") == "depois"

    def test_sem_caminho_nao_salva(self, tab):
        documento = tab()
        assert documento.save() is False

    def test_preserva_crlf(self, tab, tmp_path):
        path = tmp_path / "n.md"
        path.write_bytes("linha um\r\nlinha dois\r\n".encode("utf-8"))
        documento = tab(path)
        assert documento.eol == "\r\n"

        documento.editor.setPlainText("nova um\nnova dois\n")
        assert documento.save() is True

        bruto = path.read_bytes()
        assert bruto == "nova um\r\nnova dois\r\n".encode("utf-8")
        assert detect_eol(bruto) == "\r\n"

    def test_preserva_lf(self, tab, tmp_path):
        path = tmp_path / "n.md"
        path.write_bytes("a\nb\n".encode("utf-8"))
        documento = tab(path)
        documento.editor.setPlainText("x\ny\n")
        documento.save()
        assert path.read_bytes() == b"x\ny\n"

    def test_preserva_cp1252(self, tab, tmp_path):
        path = tmp_path / "n.md"
        path.write_bytes("Ação\r\n".encode("cp1252"))
        documento = tab(path)
        assert documento.encoding == "cp1252"

        documento.editor.setPlainText("Coração\r\n")
        assert documento.save() is True

        bruto = path.read_bytes()
        assert bruto.decode("cp1252") == "Coração\r\n"
        # Continua cp1252: "ç" é um byte só, não dois como em utf-8.
        assert len(bruto) == len("Coração\r\n")

    def test_promove_para_utf8_quando_nao_cabe(self, tab, tmp_path):
        """Arquivo cp1252 + caractere fora dele: promove em vez de falhar."""
        path = tmp_path / "n.md"
        path.write_bytes("Ação\r\n".encode("cp1252"))
        documento = tab(path)

        documento.editor.setPlainText("Ação 🎉\r\n")
        assert documento.save() is True

        assert documento.encoding == "utf-8"
        assert path.read_bytes().decode("utf-8") == "Ação 🎉\r\n"

    def test_escrita_e_atomica(self, tab, tmp_path):
        """Nenhum .tmp pode sobrar depois de salvar."""
        path = tmp_path / "n.md"
        path.write_text("x", encoding="utf-8")
        documento = tab(path)
        documento.editor.setPlainText("y")
        documento.save()

        sobrando = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert sobrando == []

    def test_salvar_como_troca_o_caminho(self, tab, tmp_path):
        documento = tab()
        documento.editor.setPlainText("# Novo\n")
        destino = tmp_path / "destino.md"

        assert documento.save_as(destino) is True
        assert documento.path == destino.resolve()
        assert destino.read_text(encoding="utf-8") == "# Novo\n"
        assert documento.is_dirty is False

    def test_salvar_em_pasta_sem_permissao_falha_limpo(self, tab, tmp_path):
        documento = tab()
        documento.editor.setPlainText("x")
        # Uma pasta que não existe: o mkstemp falha e save() devolve False,
        # em vez de deixar a exceção subir e derrubar o app.
        assert documento.save_as(tmp_path / "inexistente" / "n.md") is False


class TestRecarregar:
    def test_reload_descarta_alteracoes(self, tab, tmp_path):
        path = tmp_path / "n.md"
        path.write_text("original", encoding="utf-8")
        documento = tab(path)
        documento.editor.setPlainText("alterado")
        assert documento.is_dirty is True

        assert documento.reload() is True
        assert documento.editor.toPlainText() == "original"
        assert documento.is_dirty is False


class TestAlteracaoExterna:
    def test_detecta_mudanca(self, tab, tmp_path):
        path = tmp_path / "n.md"
        path.write_text("v1", encoding="utf-8")
        documento = tab(path)
        assert documento.check_external_change() is False

        # Garante mtime diferente mesmo em disco com resolução grosseira.
        path.write_text("v2 com mais bytes", encoding="utf-8")
        assert documento.check_external_change() is True

    def test_detecta_remocao(self, tab, tmp_path):
        path = tmp_path / "n.md"
        path.write_text("v1", encoding="utf-8")
        documento = tab(path)
        path.unlink()
        assert documento.check_external_change() is True

    def test_salvar_realinha_a_assinatura(self, tab, tmp_path):
        path = tmp_path / "n.md"
        path.write_text("v1", encoding="utf-8")
        documento = tab(path)
        documento.editor.setPlainText("v2 do editor")
        documento.save()
        assert documento.check_external_change() is False

    def test_sem_caminho_nunca_detecta(self, tab):
        assert tab().check_external_change() is False


class TestEstatisticas:
    def test_conta_linhas_palavras_caracteres(self, tab):
        documento = tab()
        documento.editor.setPlainText("uma duas três\nquatro\n")
        stats = documento.statistics()
        assert stats["lines"] == 3
        assert stats["words"] == 4
        assert stats["characters"] == len("uma duas três\nquatro\n")

    def test_documento_vazio(self, tab):
        stats = tab().statistics()
        assert stats["words"] == 0


class TestRotulo:
    def test_rotulo_customizado(self, tab):
        documento = tab()
        documento.set_untitled_label("Sem título 2")
        assert documento.display_name == "Sem título 2"
        assert documento.absolute_title == "Sem título 2"
