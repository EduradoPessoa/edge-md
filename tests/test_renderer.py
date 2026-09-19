"""Testes do pipeline de renderização.

Foco no que é fácil de quebrar em silêncio: detecção de encoding, preservação
de fim de linha, reescrita de URLs relativas e presença das extensões.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgemd.render import (
    MarkdownRenderer,
    RenderedDocument,
    decode_bytes,
    detect_eol,
    read_text_file,
    vendor_available,
)
from edgemd.render.renderer import absolutize_urls


# --------------------------------------------------------------------------
# Encoding e fim de linha
# --------------------------------------------------------------------------

class TestDecodeBytes:
    def test_utf8_simples(self):
        assert decode_bytes("ação".encode("utf-8")) == ("ação", "utf-8")

    def test_utf8_com_bom(self):
        # O BOM precisa sumir do conteúdo, senão apareceria como caractere
        # invisível no início do documento.
        texto, enc = decode_bytes(b"\xef\xbb\xbf" + "ação".encode("utf-8"))
        assert texto == "ação"
        assert enc == "utf-8-sig"

    def test_utf16_com_bom(self):
        texto, enc = decode_bytes("ação".encode("utf-16"))
        assert texto == "ação"
        assert enc == "utf-16"

    def test_cp1252_quando_nao_e_utf8(self):
        # 0xE7 é "ç" em cp1252 e sequência inválida em utf-8.
        texto, enc = decode_bytes("coração".encode("cp1252"))
        assert texto == "coração"
        assert enc == "cp1252"

    def test_cp1252_e_fallback_final(self):
        # Byte que não forma utf-8 válido em nenhum ponto.
        texto, enc = decode_bytes(b"\xff\xfe\x00dados")
        assert enc in ("utf-16", "cp1252")
        assert isinstance(texto, str)

    def test_vazio(self):
        assert decode_bytes(b"") == ("", "utf-8")


class TestDetectEol:
    @pytest.mark.parametrize(
        "payload,expected",
        [
            (b"a\r\nb\r\n", "\r\n"),
            (b"a\nb\n", "\n"),
            (b"a\r\nb\nc\r\n", "\r\n"),   # maioria decide
            (b"a\nb\nc\r\n", "\n"),
            (b"sem quebra", "\n"),         # padrão na ausência de evidência
            (b"", "\n"),
        ],
    )
    def test_deteccao(self, payload, expected):
        assert detect_eol(payload) == expected


class TestReadTextFile:
    def test_le_e_reporta(self, md_file):
        path = md_file("linha um\nlinha dois\n", eol="\r\n")
        texto, encoding, eol = read_text_file(path)
        assert texto == "linha um\r\nlinha dois\r\n"
        assert encoding == "utf-8"
        assert eol == "\r\n"

    def test_arquivo_inexistente(self, tmp_path):
        with pytest.raises(OSError):
            read_text_file(tmp_path / "nao-existe.md")


# --------------------------------------------------------------------------
# Absolutização de URLs
# --------------------------------------------------------------------------

class TestAbsolutizeUrls:
    def test_imagem_relativa(self, tmp_path):
        body = '<img src="imagens/figura.png">'
        result = absolutize_urls(body, tmp_path)
        assert result.startswith('<img src="file:///')
        assert "imagens/figura.png" in result.replace("\\", "/")

    def test_preserva_http(self, tmp_path):
        body = '<a href="https://example.com">x</a>'
        assert absolutize_urls(body, tmp_path) == body

    def test_preserva_ancora(self, tmp_path):
        body = '<a href="#secao">x</a>'
        assert absolutize_urls(body, tmp_path) == body

    def test_preserva_data_uri(self, tmp_path):
        body = '<img src="data:image/png;base64,AAAA">'
        assert absolutize_urls(body, tmp_path) == body

    def test_preserva_fragmento_em_caminho_relativo(self, tmp_path):
        result = absolutize_urls('<a href="outro.md#topo">x</a>', tmp_path)
        assert result.endswith('#topo">x</a>')

    def test_sem_base_dir_nao_altera(self):
        body = '<img src="figura.png">'
        assert absolutize_urls(body, None) == body

    def test_nao_mexe_em_texto_solto(self, tmp_path):
        # "src=" dentro de um bloco de código não pode virar URL.
        body = "<p>use src=&quot;x.png&quot; no html</p>"
        assert absolutize_urls(body, tmp_path) == body


# --------------------------------------------------------------------------
# Documento
# --------------------------------------------------------------------------

class TestRenderDocument:
    def test_titulo_vem_do_h1(self, renderer):
        doc = renderer.render_document("# Meu Título\n\ntexto")
        assert doc.title == "Meu Título"

    def test_titulo_cai_para_nome_do_arquivo(self, renderer, tmp_path):
        doc = renderer.render_document("sem título aqui", doc_path=tmp_path / "anotacoes.md")
        assert doc.title == "anotacoes"

    def test_base_dir_e_a_pasta_do_documento(self, renderer, tmp_path):
        doc = renderer.render_document("texto", doc_path=tmp_path / "sub" / "n.md")
        assert doc.base_dir == (tmp_path / "sub")

    def test_base_dir_none_sem_caminho(self, renderer):
        assert renderer.render_document("texto").base_dir is None

    def test_retorna_dataclass(self, renderer):
        assert isinstance(renderer.render_document("x"), RenderedDocument)

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_tema_no_atributo_html(self, renderer, theme):
        doc = renderer.render_document("x", theme=theme)
        assert f'data-theme="{theme}"' in doc.html

    def test_tema_invalido_cai_para_padrao(self, renderer):
        doc = renderer.render_document("x", theme="roxo")
        assert 'data-theme="dark"' in doc.html

    def test_sem_placeholder_sobrando(self, renderer):
        doc = renderer.render_document("# t\n\ntexto $x^2$ e ```py\nc\n```\n")
        assert "{{" not in doc.html
        assert "}}" not in doc.html

    def test_css_embutido(self, renderer):
        doc = renderer.render_document("x")
        assert "--bg:" in doc.html
        assert ".markdown-body" in doc.html
        assert ".code-block" in doc.html

    def test_absolutize_false_preserva_relativo(self, renderer, tmp_path):
        doc = renderer.render_document(
            "![f](img/f.png)", doc_path=tmp_path / "n.md", absolutize=False
        )
        assert 'src="img/f.png"' in doc.body

    def test_absolutize_true_reescreve(self, renderer, tmp_path):
        doc = renderer.render_document("![f](img/f.png)", doc_path=tmp_path / "n.md")
        assert "file:///" in doc.body

    def test_asset_urls_sobrescreve_vendor(self, renderer):
        doc = renderer.render_document(
            "x", asset_urls={"mermaid": "https://cdn.example/mermaid.js"}
        )
        assert "https://cdn.example/mermaid.js" in doc.html

    def test_mermaid_e_math_desligaveis(self, renderer):
        doc = renderer.render_document("```mermaid\ngraph TD\n```\n$x$", show_mermaid=False, show_math=False)
        assert "mermaid: false" in doc.html
        assert "math: false" in doc.html

    def test_script_do_webchannel_presente(self, renderer):
        # Sem ele a ponte JS<->Python não sobe e a sincronia de scroll morre.
        assert "qwebchannel.js" in renderer.render_document("x").html


# --------------------------------------------------------------------------
# Extensões do Markdown
# --------------------------------------------------------------------------

class TestExtensoes:
    def test_tabela(self, renderer):
        body = renderer.render_body("| a | b |\n|---|---|\n| 1 | 2 |\n")
        assert "<table" in body
        assert "<th>a</th>" in body

    def test_riscado(self, renderer):
        assert "<s>" in renderer.render_body("~~riscado~~")

    def test_lista_de_tarefas(self, renderer):
        body = renderer.render_body("- [x] feito\n- [ ] pendente\n")
        assert "task-list-item" in body

    def test_nota_de_rodape(self, renderer):
        body = renderer.render_body("texto[^1]\n\n[^1]: nota\n")
        assert "footnote" in body

    def test_lista_de_definicao(self, renderer):
        body = renderer.render_body("Termo\n: Definição\n")
        assert "<dl" in body and "<dt" in body and "<dd" in body

    def test_ancoras_de_titulo(self, renderer):
        body = renderer.render_body("## Seção com Acentos\n")
        assert 'id="secao-com-acentos"' in body

    def test_matematica_inline_e_bloco(self, renderer):
        inline = renderer.render_body("texto $a+b$ fim")
        assert 'class="math inline"' in inline

        bloco = renderer.render_body("$$\nx = 1\n$$\n")
        assert 'class="math block"' in bloco

    def test_matematica_protegida_da_enfase(self, renderer):
        # Sem o plugin dollarmath, o "_" da fórmula viraria itálico.
        body = renderer.render_body("$x_i^2$")
        assert "<em>" not in body
        assert "x_i^2" in body

    def test_bloco_mermaid_vira_diagrama(self, renderer):
        body = renderer.render_body("```mermaid\ngraph TD\n  A-->B\n```\n")
        assert 'data-diagram="mermaid"' in body
        assert "<svg" not in body  # o desenho é feito no cliente, pelo JS

    def test_bloco_de_codigo_com_botao_copiar(self, renderer):
        body = renderer.render_body("```python\nx = 1\n```\n")
        assert "data-copy" in body
        assert "language-python" in body
        assert ">python<" in body  # rótulo da linguagem

    def test_realce_aplicado(self, renderer):
        body = renderer.render_body("```python\ndef f():\n    return 1\n```\n")
        # O Pygments envolve tokens em spans com classes.
        assert 'class="k"' in body or 'class="nf"' in body

    def test_linguagem_desconhecida_nao_quebra(self, renderer):
        body = renderer.render_body("```linguagem-inexistente\nconteudo\n```\n")
        assert "data-copy" in body
        assert "conteudo" in body

    def test_bloco_sem_linguagem(self, renderer):
        body = renderer.render_body("```\ncodigo puro\n```\n")
        assert "codigo puro" in body
        assert ">texto<" in body  # rótulo padrão

    def test_html_cru_e_respeitado(self, renderer):
        body = renderer.render_body("<div class='x'>cru</div>")
        assert "<div class='x'>cru</div>" in body

    def test_data_line_para_sincronia(self, renderer):
        body = renderer.render_body("# Um\n\ntexto\n\n## Dois\n")
        assert 'data-line="1"' in body
        assert 'data-line="5"' in body

    def test_escape_de_html_no_codigo(self, renderer):
        # Sem escapar, um "<script>" dentro do bloco viraria marcação de verdade.
        body = renderer.render_body("```\n<script>alert(1)</script>\n```\n")
        assert "&lt;script&gt;" in body


# --------------------------------------------------------------------------
# Vendor
# --------------------------------------------------------------------------

class TestVendor:
    def test_mermaid_e_katex_presentes(self):
        # Se este teste falhar, rode: python tools/fetch_vendor.py
        disponivel = vendor_available()
        assert disponivel["mermaid"], "mermaid.min.js ausente"
        assert disponivel["katex"], "katex.min.js ausente"
        assert disponivel["katex_css"], "katex.min.css ausente"

    def test_versao_do_manifesto(self):
        from edgemd.export import vendor_versions

        versions = vendor_versions()
        assert "mermaid" in versions
        assert "katex" in versions
        # Mermaid 12 mudou a API de render; o preview.js usa a da v11.
        assert versions["mermaid"].split(".")[0] == "11"


# --------------------------------------------------------------------------
# Codificação de arquivo real
# --------------------------------------------------------------------------

class TestArquivoReal:
    def test_ida_e_volta_utf8(self, renderer, md_file):
        path = md_file("# Café\n\nAção e coração.\n", encoding="utf-8", eol="\n")
        texto, encoding, eol = read_text_file(path)
        assert "Café" in texto
        assert encoding == "utf-8"
        assert eol == "\n"

    def test_ida_e_volta_cp1252(self, renderer, md_file):
        path = md_file("# Café\n\nAção.\n", encoding="cp1252", eol="\r\n")
        texto, encoding, eol = read_text_file(path)
        assert "Café" in texto
        assert encoding == "cp1252"
        assert eol == "\r\n"

    def test_renderiza_arquivo_cp1252(self, renderer, md_file):
        path = md_file("# Ação\n\nTexto com acentuação.\n", encoding="cp1252")
        texto, _enc, _eol = read_text_file(path)
        doc = renderer.render_document(texto, doc_path=path)
        assert "Ação" in doc.html
