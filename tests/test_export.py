"""Testes da exportação para HTML.

O objetivo de uma exportação é um arquivo que funcione em **outra** máquina.
Por isso os testes verificam principalmente que nada aponta para caminhos
locais: nem imagens, nem as bibliotecas de diagrama e fórmula.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest

from edgemd.export import cdn_urls, embed_images, export_html, vendor_versions

pytest.importorskip("PyQt6.QtWebEngineCore")

#: PNG 1x1 válido, para não depender do Pillow nos testes.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)


class TestEmbedImages:
    def test_embute_imagem_local(self, tmp_path):
        (tmp_path / "f.png").write_bytes(TINY_PNG)
        body, ok, falhas = embed_images('<img src="f.png">', tmp_path)
        assert ok == 1
        assert falhas == 0
        assert "data:image/png;base64," in body
        assert 'src="f.png"' not in body

    def test_conta_imagem_ausente(self, tmp_path):
        body, ok, falhas = embed_images('<img src="sumiu.png">', tmp_path)
        assert ok == 0
        assert falhas == 1
        # A referência original é preservada, então o HTML ainda abre.
        assert 'src="sumiu.png"' in body

    def test_subpasta(self, tmp_path):
        (tmp_path / "imagens").mkdir()
        (tmp_path / "imagens" / "f.png").write_bytes(TINY_PNG)
        body, ok, _ = embed_images('<img src="imagens/f.png">', tmp_path)
        assert ok == 1
        assert "base64," in body

    def test_nao_mexe_em_remota(self, tmp_path):
        body, ok, _ = embed_images('<img src="https://x.com/a.png">', tmp_path)
        assert ok == 0
        assert body == '<img src="https://x.com/a.png">'

    def test_nao_mexe_em_data_uri(self, tmp_path):
        original = '<img src="data:image/png;base64,AAAA">'
        body, ok, _ = embed_images(original, tmp_path)
        assert body == original

    def test_aceita_aspas_simples_ausentes(self, tmp_path):
        # Sem aspas o regex não casa; o importante é não corromper o HTML.
        original = "<img src=f.png>"
        body, _, _ = embed_images(original, tmp_path)
        assert body == original


class TestCdn:
    def test_usa_versao_do_manifesto(self):
        urls = cdn_urls()
        versions = vendor_versions()
        assert versions["mermaid"] in urls["mermaid"]
        assert versions["katex"] in urls["katex"]

    def test_mermaid_na_linha_11(self):
        # A API de render mudou na 12; o preview.js depende da v11.
        assert "mermaid@11" in cdn_urls()["mermaid"]


class TestExportHtml:
    def test_gera_arquivo(self, renderer, tmp_path):
        origem = tmp_path / "nota.md"
        origem.write_text("# Título\n\ntexto\n", encoding="utf-8")
        destino = tmp_path / "saida.html"

        resultado = export_html(renderer, "# Título\n\ntexto\n", origem, destino)

        assert destino.is_file()
        assert resultado.target == destino.resolve()
        assert resultado.size > 0
        assert resultado.size_label

    def test_preserva_caminhos_relativos(self, renderer, tmp_path):
        """O HTML exportado não pode apontar para pastas desta máquina."""
        origem = tmp_path / "nota.md"
        origem.write_text("![f](imagens/f.png)\n", encoding="utf-8")

        resultado = export_html(
            renderer,
            "![f](imagens/f.png)\n",
            origem,
            tmp_path / "saida.html",
            embed_local_images=False,
        )
        html = Path(resultado.target).read_text(encoding="utf-8")

        assert 'src="imagens/f.png"' in html
        assert "file:///" not in html or "file:///cdn" in html

    def test_nao_vaza_file_url(self, renderer, tmp_path):
        origem = tmp_path / "nota.md"
        origem.write_text("texto\n", encoding="utf-8")
        destino = tmp_path / "saida.html"

        export_html(renderer, "texto\n", origem, destino)
        html = destino.read_text(encoding="utf-8")

        # Nenhum asset do app pode ter ficado como caminho local.
        assert str(tmp_path).replace("\\", "/") not in html
        assert "cdn.jsdelivr.net" in html

    def test_remove_script_do_webchannel(self, renderer, tmp_path):
        """O arquivo abre no navegador do usuário, onde o qrc: não existe."""
        destino = tmp_path / "saida.html"
        export_html(renderer, "texto\n", tmp_path / "n.md", destino)
        html = destino.read_text(encoding="utf-8")
        assert "qwebchannel.js" not in html

    @pytest.mark.parametrize("tema", ["light", "dark"])
    def test_tema_aplicado(self, renderer, tmp_path, tema):
        destino = tmp_path / f"{tema}.html"
        export_html(renderer, "# t\n", tmp_path / "n.md", destino, theme=tema)
        html = destino.read_text(encoding="utf-8")
        assert f'data-theme="{tema}"' in html

    def test_embute_imagem_e_conta(self, renderer, tmp_path):
        (tmp_path / "imagens").mkdir()
        (tmp_path / "imagens" / "f.png").write_bytes(TINY_PNG)
        origem = tmp_path / "nota.md"
        origem.write_text("![f](imagens/f.png)\n", encoding="utf-8")
        destino = tmp_path / "saida.html"

        resultado = export_html(
            renderer, "![f](imagens/f.png)\n", origem, destino
        )

        assert resultado.embedded == 1
        assert resultado.failed == 0
        assert "base64," in destino.read_text(encoding="utf-8")

    def test_conta_imagem_ausente(self, renderer, tmp_path):
        origem = tmp_path / "nota.md"
        origem.write_text("![f](nao-existe.png)\n", encoding="utf-8")
        resultado = export_html(
            renderer, "![f](nao-existe.png)\n", origem, tmp_path / "s.html"
        )
        assert resultado.failed == 1

    def test_css_embutido_para_funcionar_sozinho(self, renderer, tmp_path):
        destino = tmp_path / "s.html"
        export_html(renderer, "# t\n", tmp_path / "n.md", destino)
        html = destino.read_text(encoding="utf-8")
        assert "--bg:" in html
        assert "<style>" in html

    def test_diagrama_e_formula_preservados(self, renderer, tmp_path):
        texto = "```mermaid\ngraph TD\n  A-->B\n```\n\n$x^2$\n"
        destino = tmp_path / "s.html"
        export_html(renderer, texto, tmp_path / "n.md", destino)
        html = destino.read_text(encoding="utf-8")

        assert 'data-diagram="mermaid"' in html
        assert "mermaid: true" in html
        assert "math: true" in html

    def test_modo_offline_usa_arquivos_locais(self, renderer, tmp_path):
        """Sem CDN, o HTML só funciona nesta máquina — mas precisa funcionar."""
        from edgemd.paths import asset_path
        from edgemd.render.renderer import _file_url

        destino = tmp_path / "s.html"
        documento = renderer.render_document(
            "```mermaid\ngraph TD\n A-->B\n```\n",
            doc_path=tmp_path / "n.md",
            theme="dark",
        )
        assert _file_url(asset_path("vendor", "mermaid.min.js")) in documento.html

    def test_pasta_de_destino_inexistente_levanta_oserror(self, renderer, tmp_path):
        with pytest.raises(OSError):
            export_html(
                renderer, "x", tmp_path / "n.md", tmp_path / "nao" / "existe" / "s.html"
            )

    def test_html_bem_formado(self, renderer, tmp_path):
        destino = tmp_path / "s.html"
        export_html(renderer, "# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", tmp_path / "n.md", destino)
        html = destino.read_text(encoding="utf-8")

        assert html.startswith("<!DOCTYPE html>")
        assert html.rstrip().endswith("</html>")
        assert re.search(r'<meta charset="utf-8">', html)
