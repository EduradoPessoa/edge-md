"""Testes das preferências.

Todos usam um escopo isolado: sem isso a suíte gravaria no registro real do
Windows e apagaria as preferências de quem está desenvolvendo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgemd.config import MAX_RECENT_FILES, AppConfig


@pytest.fixture
def config(tmp_path) -> AppConfig:
    """Config isolada, num arquivo dentro do tmp_path do teste.

    Fica sob tmp_path de propósito: o pytest apaga a pasta ao fim de cada
    teste, então nenhum estado vaza de uma execução para a seguinte.
    """
    return AppConfig(settings_path=tmp_path / "settings.ini")


class TestPadroes:
    def test_tema_padrao(self, config):
        assert config.theme in ("light", "dark")

    def test_booleano_padrao(self, config):
        # Bug clássico: QSettings devolve string e "False" é truthy.
        assert isinstance(config.sidebar_visible, bool)
        assert isinstance(config.close_to_tray, bool)
        assert isinstance(config.scroll_sync, bool)


class TestTipagem:
    def test_ida_e_volta_de_bool(self, config):
        config.close_to_tray = False
        assert config.close_to_tray is False
        config.close_to_tray = True
        assert config.close_to_tray is True

    def test_ida_e_volta_de_int(self, config):
        config.editor_font_size = 18
        assert config.editor_font_size == 18

    def test_tema_invalido_e_rejeitado(self, config):
        config.theme = "roxo"
        assert config.theme in ("light", "dark")


class TestLimites:
    @pytest.mark.parametrize("valor", [0, 2, 999, -5])
    def test_tamanho_de_fonte_respeita_limites(self, config, valor):
        config.editor_font_size = valor
        assert 8 <= config.editor_font_size <= 32

    @pytest.mark.parametrize("valor", [1, 5000])
    def test_atraso_de_render_respeita_limites(self, config, valor):
        config.render_delay_ms = valor
        assert 60 <= config.render_delay_ms <= 2000

    def test_largura_de_conteudo_respeita_limites(self, config):
        config.content_width = 5
        assert config.content_width >= 30


class TestRecentes:
    def test_adiciona_e_ordena(self, config, tmp_path):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text("a", encoding="utf-8")
        b.write_text("b", encoding="utf-8")

        config.add_recent_file(a)
        config.add_recent_file(b)
        # O mais recente vem primeiro.
        assert Path(config.recent_files[0]) == b.resolve()
        assert Path(config.recent_files[1]) == a.resolve()

    def test_nao_duplica(self, config, tmp_path):
        a = tmp_path / "a.md"
        a.write_text("a", encoding="utf-8")
        config.add_recent_file(a)
        config.add_recent_file(a)
        assert len(config.recent_files) == 1

    def test_reabrir_move_para_o_topo(self, config, tmp_path):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text("a", encoding="utf-8")
        b.write_text("b", encoding="utf-8")
        config.add_recent_file(a)
        config.add_recent_file(b)
        config.add_recent_file(a)
        assert Path(config.recent_files[0]) == a.resolve()

    def test_descarta_arquivo_apagado(self, config, tmp_path):
        a = tmp_path / "a.md"
        a.write_text("a", encoding="utf-8")
        config.add_recent_file(a)
        a.unlink()
        # A lista filtra na leitura, então um arquivo removido não reaparece.
        assert config.recent_files == []

    def test_respeita_o_maximo(self, config, tmp_path):
        for index in range(MAX_RECENT_FILES + 5):
            path = tmp_path / f"n{index}.md"
            path.write_text("x", encoding="utf-8")
            config.add_recent_file(path)
        assert len(config.recent_files) == MAX_RECENT_FILES

    def test_limpar(self, config, tmp_path):
        a = tmp_path / "a.md"
        a.write_text("a", encoding="utf-8")
        config.add_recent_file(a)
        config.clear_recent_files()
        assert config.recent_files == []

    def test_remover_individual(self, config, tmp_path):
        a = tmp_path / "a.md"
        a.write_text("a", encoding="utf-8")
        config.add_recent_file(a)
        config.remove_recent_file(a)
        assert config.recent_files == []


class TestSessao:
    def test_sessao_ignora_arquivos_inexistentes(self, config, tmp_path):
        existente = tmp_path / "existe.md"
        existente.write_text("x", encoding="utf-8")
        config.session_files = [str(existente), str(tmp_path / "sumiu.md")]
        assert config.session_files == [str(existente)]

    def test_sessao_vazia(self, config):
        assert config.session_files == []


class TestUltimoDiretorio:
    def test_cai_para_uma_pasta_existente(self, config):
        # O fallback não pode devolver um caminho inexistente: em máquinas com
        # OneDrive, ~/Documents costuma não existir.
        assert config.last_directory.is_dir()

    def test_define_diretorio(self, config, tmp_path):
        config.last_directory = tmp_path
        assert config.last_directory == tmp_path

    def test_diretorio_invalido_e_ignorado(self, config, tmp_path):
        config.last_directory = tmp_path
        config.last_directory = tmp_path / "nao-existe"
        assert config.last_directory == tmp_path
