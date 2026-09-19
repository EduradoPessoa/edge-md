"""Testes dos modelos para novos documentos.

A pasta de modelos vem do ``QStandardPaths``, que não é redirecionável por
variável de ambiente. Por isso os testes trocam ``templates.templates_dir`` por
uma pasta temporária — a função é o único ponto que toca o disco, e trocá-la
mantém os modelos reais do usuário fora do teste.
"""

from __future__ import annotations

import re
from datetime import datetime

import pytest

from edgemd import templates
from edgemd.templates import Template

pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    """Redireciona a pasta de modelos para o tmp_path."""
    destino = tmp_path / "templates"
    destino.mkdir()
    monkeypatch.setattr(templates, "templates_dir", lambda: destino)
    return destino


# --------------------------------------------------------------------------
# Embutidos
# --------------------------------------------------------------------------

class TestEmbutidos:
    def test_existem(self):
        assert templates.builtin_templates()

    def test_todos_tem_conteudo(self):
        for modelo in templates.builtin_templates():
            assert modelo.content.strip(), f"{modelo.name} está vazio"

    def test_todos_tem_descricao(self):
        """A descrição é o que o seletor mostra; sem ela, o nome tem de bastar."""
        for modelo in templates.builtin_templates():
            assert modelo.description.strip(), f"{modelo.name} sem descrição"

    def test_nao_sao_editaveis(self):
        for modelo in templates.builtin_templates():
            assert modelo.is_builtin is True
            assert modelo.editable is False
            assert modelo.path is None

    def test_tem_titulo(self):
        for modelo in templates.builtin_templates():
            assert modelo.content.lstrip().startswith("#"), modelo.name


# --------------------------------------------------------------------------
# Listagem
# --------------------------------------------------------------------------

class TestListagem:
    def test_sem_modelos_do_usuario(self, pasta):
        assert templates.user_templates() == []

    def test_so_embutidos_na_lista(self, pasta):
        lista = templates.all_templates(include_blank=False)
        assert len(lista) == len(templates.builtin_templates())

    def test_em_branco_vem_primeiro(self, pasta):
        lista = templates.all_templates(include_blank=True)
        assert lista[0].name == "Em branco"
        assert lista[0].content == ""

    def test_usuario_vem_antes_dos_embutidos(self, pasta):
        """Quem criou um modelo quer achá-lo, não procurá-lo embaixo."""
        templates.save("Meu modelo", "# meu\n")
        lista = templates.all_templates(include_blank=False)
        assert lista[0].name == "Meu modelo"

    def test_ordem_alfabetica_entre_os_do_usuario(self, pasta):
        for nome in ("Zebra", "alfa", "Meio"):
            templates.save(nome, "# x\n")
        nomes = [m.name for m in templates.user_templates()]
        assert nomes == ["alfa", "Meio", "Zebra"]

    def test_so_arquivos_md(self, pasta):
        templates.save("valido", "# x\n")
        (pasta / "anotacao.txt").write_text("não é modelo", encoding="utf-8")
        (pasta / "rascunho.md.bak").write_text("não é modelo", encoding="utf-8")
        assert [m.name for m in templates.user_templates()] == ["valido"]

    def test_pasta_inexistente_nao_explode(self, tmp_path, monkeypatch):
        monkeypatch.setattr(templates, "templates_dir", lambda: tmp_path / "sumiu")
        assert templates.user_templates() == []


# --------------------------------------------------------------------------
# Gravação
# --------------------------------------------------------------------------

class TestGravacao:
    def test_salva_e_le(self, pasta):
        templates.save("Ata", "# Ata\n\nconteúdo\n")
        modelo = templates.find("Ata")
        assert modelo is not None
        assert "conteúdo" in modelo.content
        assert modelo.editable is True

    def test_garante_quebra_no_fim(self, pasta):
        """Sem a quebra final, o cursor do editor fica colado na última linha."""
        caminho = templates.save("Sem fim", "# x")
        assert caminho.read_text(encoding="utf-8").endswith("\n")

    def test_nao_duplica_quebra(self, pasta):
        caminho = templates.save("Com fim", "# x\n")
        assert caminho.read_text(encoding="utf-8") == "# x\n"

    def test_sobrescreve(self, pasta):
        templates.save("X", "# primeiro\n")
        templates.save("X", "# segundo\n")
        assert "segundo" in templates.find("X").content
        assert len(templates.user_templates()) == 1

    def test_nome_com_dois_pontos(self, pasta):
        """':' é proibido no Windows e viraria subpasta ou erro."""
        caminho = templates.save("Ata: 2026", "# x\n")
        assert ":" not in caminho.name
        assert templates.find("Ata: 2026").content

    def test_nome_com_barra(self, pasta):
        caminho = templates.save("a/b", "# x\n")
        assert "/" not in caminho.name
        assert (pasta / caminho.name).parent == pasta

    def test_nome_so_com_invalidos(self, pasta):
        caminho = templates.save("///", "# x\n")
        assert caminho.name == "modelo.md"

    def test_nome_vazio_vira_modelo(self, pasta):
        assert templates.save("", "# x\n").name == "modelo.md"

    def test_espacos_normalizados(self, pasta):
        assert templates.save("Meu    modelo", "# x\n").name == "Meu modelo.md"

    def test_encoding_utf8(self, pasta):
        """Acentos precisam sobreviver à ida e volta."""
        templates.save("Ação", "# Ação e coração\n")
        assert "Ação" in templates.find("Ação").content

    @pytest.mark.parametrize("nome", ["<>", '"aspas"', "interrogação?", "pipe|", "asterisco*"])
    def test_nomes_proibidos_no_windows(self, pasta, nome):
        caminho = templates.save(nome, "# x\n")
        assert not re.search(r'[<>:"/\\|?*]', caminho.name)


# --------------------------------------------------------------------------
# Busca e remoção
# --------------------------------------------------------------------------

class TestBusca:
    def test_acha_do_usuario(self, pasta):
        templates.save("Meu", "# x\n")
        assert templates.find("Meu") is not None

    def test_acha_embutido(self, pasta):
        assert templates.find("Diário") is not None

    def test_nome_vazio_e_em_branco(self, pasta):
        modelo = templates.find("")
        assert modelo is not None
        assert modelo.content == ""

    def test_inexistente(self, pasta):
        assert templates.find("não existe") is None

    def test_exists(self, pasta):
        templates.save("Sim", "# x\n")
        assert templates.exists("Sim") is True
        assert templates.exists("Não") is False


class TestRemocao:
    def test_remove_do_usuario(self, pasta):
        templates.save("Temporário", "# x\n")
        assert templates.delete("Temporário") is True
        assert templates.find("Temporário") is None

    def test_nao_remove_embutido(self, pasta):
        """Embutido não tem arquivo; remover só o faria sumir até reiniciar."""
        assert templates.delete("Diário") is False
        assert templates.find("Diário") is not None

    def test_remover_inexistente(self, pasta):
        assert templates.delete("nada") is False

    def test_remove_o_arquivo(self, pasta):
        caminho = templates.save("X", "# x\n")
        templates.delete("X")
        assert not caminho.exists()

    def test_renomeia(self, pasta):
        templates.save("Antigo", "# x\n")
        assert templates.rename("Antigo", "Novo") is True
        assert templates.find("Antigo") is None
        assert templates.find("Novo") is not None

    def test_renomear_para_existente_falha(self, pasta):
        templates.save("A", "# a\n")
        templates.save("B", "# b\n")
        assert templates.rename("A", "B") is False
        assert "a" in templates.find("A").content

    def test_renomear_embutido_falha(self, pasta):
        assert templates.rename("Diário", "Outro") is False


# --------------------------------------------------------------------------
# Expansão de marcadores
# --------------------------------------------------------------------------

class TestExpansao:
    def test_data(self):
        texto, _ = templates.expand("Feito em {data}.")
        assert datetime.now().strftime("%d/%m/%Y") in texto
        assert "{data}" not in texto

    def test_data_iso(self):
        texto, _ = templates.expand("{data_iso}")
        assert datetime.now().strftime("%Y-%m-%d") in texto

    def test_hora(self):
        texto, _ = templates.expand("{hora}")
        assert re.fullmatch(r"\d{2}:\d{2}", texto)

    def test_assunto(self):
        texto, _ = templates.expand("# {assunto}", title="Vendas")
        assert texto == "# Vendas"

    def test_assunto_sem_titulo(self):
        """Sem título, o marcador vira um espaço em branco a preencher."""
        texto, _ = templates.expand("# {assunto}")
        assert texto == "# assunto"

    def test_sem_marcador_nao_muda(self):
        original = "# Título\n\ntexto comum\n"
        texto, _ = templates.expand(original)
        assert texto == original

    def test_quebra_duplicada_nao_afeta(self):
        texto, _ = templates.expand("sem marcador")
        assert texto == "sem marcador"

    def test_cursor_na_primeira_linha_vazia(self):
        _texto, posicao = templates.expand("# Título\n\ncorpo\n")
        # Logo depois do "\n" do título, que é onde o usuário escreveria.
        assert posicao == len("# Título\n")

    def test_cursor_no_fim_sem_linha_vazia(self):
        texto = "# Título"
        _t, posicao = templates.expand(texto)
        assert posicao == len(texto)

    def test_cursor_dentro_do_documento(self):
        """Não pode cair na última quebra, que não tem para onde escrever."""
        _t, posicao = templates.expand("# T\n\n## Seção\n")
        assert 0 < posicao < len("# T\n\n## Seção\n")


class TestModelosEmbutidosExpandem:
    @pytest.mark.parametrize("nome", list(templates.BUILTIN))
    def test_sem_marcador_sobrando(self, nome):
        """Um marcador não substituído apareceria literalmente no documento."""
        modelo = templates.BUILTIN[nome]
        texto, _ = templates.expand(modelo[1], title="Teste")
        assert "{" not in texto, f"{nome} deixou marcador: {texto[:80]}"
        assert "}" not in texto, f"{nome} deixou marcador: {texto[:80]}"

    @pytest.mark.parametrize("nome", list(templates.BUILTIN))
    def test_cursor_dentro_dos_limites(self, nome):
        texto, posicao = templates.expand(templates.BUILTIN[nome][1])
        assert 0 <= posicao <= len(texto)


# --------------------------------------------------------------------------
# Template
# --------------------------------------------------------------------------

class TestDataclass:
    def test_first_line(self):
        modelo = Template(name="X", content="# Título\n\ncorpo")
        assert modelo.first_line() == "# Título"

    def test_first_line_ignora_linhas_vazias(self):
        modelo = Template(name="X", content="\n\n  \ntexto")
        assert modelo.first_line() == "texto"

    def test_first_line_vazio(self):
        assert Template(name="X", content="").first_line() == ""

    def test_first_line_trunca(self):
        modelo = Template(name="X", content="a" * 200)
        assert len(modelo.first_line()) == 80
