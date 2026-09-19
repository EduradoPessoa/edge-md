"""Testes da inserção de imagens.

A lógica pura está aqui; o diálogo e a barra de ferramentas são verificados em
``test_insert_actions.py``. O foco é o caminho escrito no documento: é ele que
decide se as imagens aparecem em outra máquina ou não.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgemd.image_insert import (
    IMAGE_SUFFIXES,
    is_inside,
    markdown_url,
    prepare_image,
    relative_url,
    unique_target,
)

PNG = b"\x89PNG\r\n\x1a\nfalso"
OUTRO_PNG = b"\x89PNG\r\n\x1a\noutro"


@pytest.fixture
def projeto(tmp_path):
    """Documento numa pasta com espaço no nome, e uma pasta de downloads."""
    documentos = tmp_path / "Meus Documentos"
    documentos.mkdir()
    documento = documentos / "nota.md"
    documento.write_text("# nota\n", encoding="utf-8")

    downloads = tmp_path / "Downloads"
    downloads.mkdir()

    return documento, documentos, downloads


def imagem(diretorio: Path, nome: str = "figura.png", dados: bytes = PNG) -> Path:
    caminho = diretorio / nome
    caminho.write_bytes(dados)
    return caminho


# --------------------------------------------------------------------------
# URL do Markdown
# --------------------------------------------------------------------------

class TestMarkdownUrl:
    def test_barras_invertidas_viram_normais(self):
        assert markdown_url(r"imagens\figura.png") == "imagens/figura.png"

    def test_espaco_e_codificado(self):
        assert markdown_url("Meus Documentos/a.png") == "Meus%20Documentos/a.png"

    def test_cerquilha_e_codificada(self):
        """# numa URL é âncora; cru, partiria o link ao meio."""
        assert markdown_url("a#b.png") == "a%23b.png"

    def test_percentual_nao_e_codificado_duas_vezes(self):
        """Bug real: escapar o espaço antes do % produzia %2520.

        A ordem de substituição não pode importar — por isso a codificação é
        feita numa passada só, e não percorrendo a tabela em sequência.
        """
        assert markdown_url("100% e espaço.png") == "100%25%20e%20espaço.png"

    def test_acento_fica_legivel(self):
        """Acentuação não é codificada: 'ação.png' é mais legível que '%C3%A7'."""
        assert markdown_url("ação.png") == "ação.png"

    def test_espaco_vira_vinte(self):
        assert markdown_url("a b.png") == "a%20b.png"

    def test_interrogacao_e_colchetes(self):
        assert markdown_url("a#b?c.png") == "a%23b%3Fc.png"
        assert markdown_url("a[b].png") == "a%5Bb%5D.png"

    def test_sem_caractere_especial_fica_igual(self):
        assert markdown_url("imagens/figura.png") == "imagens/figura.png"

    def test_nao_codifica_barra(self):
        assert markdown_url("a/b/c.png") == "a/b/c.png"


class TestIsInside:
    def test_dentro(self, projeto):
        _, documentos, _ = projeto
        assert is_inside(documentos / "a.png", documentos) is True

    def test_fora(self, projeto):
        _, documentos, downloads = projeto
        assert is_inside(downloads / "a.png", documentos) is False

    def test_pasta_igual(self, projeto):
        _, documentos, _ = projeto
        assert is_inside(documentos, documentos) is True

    def test_subpasta(self, projeto):
        _, documentos, _ = projeto
        sub = documentos / "imagens"
        sub.mkdir()
        assert is_inside(sub / "a.png", documentos) is True

    def test_pasta_irma_com_prefixo_parecido(self, tmp_path):
        """'Projeto2' não pode contar como dentro de 'Projeto'."""
        (tmp_path / "Projeto").mkdir()
        (tmp_path / "Projeto2").mkdir()
        assert is_inside(tmp_path / "Projeto2" / "a.png", tmp_path / "Projeto") is False


class TestRelativeUrl:
    def test_mesma_pasta(self, projeto):
        _, documentos, _ = projeto
        assert relative_url(documentos / "a.png", documentos) == "a.png"

    def test_subpasta(self, projeto):
        _, documentos, _ = projeto
        assert relative_url(documentos / "imagens" / "a.png", documentos) == "imagens/a.png"

    def test_usa_barra_normal(self, projeto):
        _, documentos, _ = projeto
        assert "\\" not in relative_url(documentos / "a.png", documentos)


# --------------------------------------------------------------------------
# Destino da cópia
# --------------------------------------------------------------------------

class TestUniqueTarget:
    def test_nome_livre(self, tmp_path):
        origem = imagem(tmp_path, "a.png")
        destino = tmp_path / "destino"
        destino.mkdir()
        assert unique_target(destino, "a.png", origem).name == "a.png"

    def test_mesmo_conteudo_reaproveita(self, tmp_path):
        """Inserir a mesma imagem duas vezes não deve criar a-2.png."""
        origem = imagem(tmp_path, "a.png")
        destino = tmp_path / "destino"
        destino.mkdir()
        (destino / "a.png").write_bytes(PNG)
        assert unique_target(destino, "a.png", origem).name == "a.png"

    def test_conteudo_diferente_ganha_sufixo(self, tmp_path):
        """Sobrescrever apagaria uma imagem que o documento já usa."""
        origem = imagem(tmp_path, "a.png")
        destino = tmp_path / "destino"
        destino.mkdir()
        (destino / "a.png").write_bytes(OUTRO_PNG)
        assert unique_target(destino, "a.png", origem).name == "a-2.png"

    def test_sufixo_avanca_ate_achar_livre(self, tmp_path):
        origem = imagem(tmp_path, "a.png")
        destino = tmp_path / "destino"
        destino.mkdir()
        (destino / "a.png").write_bytes(OUTRO_PNG)
        (destino / "a-2.png").write_bytes(OUTRO_PNG)
        assert unique_target(destino, "a.png", origem).name == "a-3.png"


# --------------------------------------------------------------------------
# Prepara a imagem
# --------------------------------------------------------------------------

class TestPrepareImagemDentro:
    def test_nao_copia(self, projeto):
        documento, documentos, _ = projeto
        figura = imagem(documentos, "local.png")
        resultado = prepare_image(figura, documento)

        assert resultado.was_copied is False
        assert resultado.url == "local.png"
        assert resultado.relative is True

    def test_em_subpasta(self, projeto):
        documento, documentos, _ = projeto
        sub = documentos / "imagens"
        sub.mkdir()
        figura = imagem(sub, "local.png")
        assert prepare_image(figura, documento).url == "imagens/local.png"


class TestPrepareImagemFora:
    def test_copia_para_imagens(self, projeto):
        documento, documentos, downloads = projeto
        figura = imagem(downloads, "foto.png")

        resultado = prepare_image(figura, documento)

        assert resultado.was_copied is True
        assert resultado.url == "imagens/foto.png"
        assert (documentos / "imagens" / "foto.png").is_file()

    def test_conteudo_preservado(self, projeto):
        documento, documentos, downloads = projeto
        figura = imagem(downloads, "foto.png")
        prepare_image(figura, documento)
        assert (documentos / "imagens" / "foto.png").read_bytes() == PNG

    def test_nome_com_espaco(self, projeto):
        """Espaço no nome vira %20 na URL, mas o arquivo mantém o nome."""
        documento, documentos, downloads = projeto
        figura = imagem(downloads, "foto legal.png")

        resultado = prepare_image(figura, documento)

        assert resultado.url == "imagens/foto%20legal.png"
        assert (documentos / "imagens" / "foto legal.png").is_file()

    def test_sem_copiar_usa_caminho_absoluto(self, projeto):
        documento, _, downloads = projeto
        figura = imagem(downloads, "foto.png")

        resultado = prepare_image(figura, documento, copy_external=False)

        assert resultado.was_copied is False
        assert resultado.relative is False
        assert "Downloads" in resultado.url

    def test_reinserir_reaproveita(self, projeto):
        documento, documentos, downloads = projeto
        figura = imagem(downloads, "foto.png")
        prepare_image(figura, documento)
        prepare_image(figura, documento)

        copiados = sorted(p.name for p in (documentos / "imagens").iterdir())
        assert copiados == ["foto.png"]

    def test_alt_vem_do_nome(self, projeto):
        documento, _, downloads = projeto
        figura = imagem(downloads, "diagrama de rede.png")
        assert prepare_image(figura, documento).alt == "diagrama de rede"


class TestPrepareSemDocumento:
    def test_sem_arquivo_salvo_usa_absoluto(self, projeto):
        _, _, downloads = projeto
        figura = imagem(downloads, "foto.png")

        resultado = prepare_image(figura, None)

        assert resultado.relative is False
        assert "Downloads" in resultado.url

    def test_nao_copia(self, projeto):
        _, documentos, downloads = projeto
        figura = imagem(downloads, "foto.png")
        prepare_image(figura, None)
        assert not (documentos / "imagens").exists()


class TestErros:
    def test_arquivo_ausente(self, projeto, tmp_path):
        documento, _, _ = projeto
        with pytest.raises(OSError):
            prepare_image(tmp_path / "nao-existe.png", documento)

    def test_pasta_em_vez_de_arquivo(self, projeto):
        documento, _, downloads = projeto
        with pytest.raises(OSError):
            prepare_image(downloads, documento)


class TestFormatos:
    def test_cobre_os_comuns(self):
        for extensao in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
            assert extensao in IMAGE_SUFFIXES

    def test_sem_repeticao(self):
        assert len(IMAGE_SUFFIXES) == len(set(IMAGE_SUFFIXES))
