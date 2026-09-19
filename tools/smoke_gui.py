"""Verificação de ponta a ponta da interface.

Abre o ``docs-exemplo/demo.md``, espera renderizar e **inspeciona o DOM** que o
Chromium produziu: blocos de código, diagramas Mermaid desenhados, fórmulas
convertidas pelo KaTeX, imagens carregadas, botões de copiar. Também grava PNGs
do preview e da janela, para conferência visual e para a documentação.

Este é o teste que prova que o app funciona. A suíte de ``pytest`` cobre a
lógica pura (render, encoding, gravação atômica, IPC, registro), mas não vê o
que sai na tela — e foi justamente aí que apareceram os bugs mais caros desta
implementação (painel de preview com largura zero e uma exceção de JavaScript
que matava a sincronia de rolagem).

Uso:
    python tools/smoke_gui.py                          # headless
    $env:SMOKE_THEME='dark'; python tools/smoke_gui.py
    $env:SMOKE_WINDOW='1';   python tools/smoke_gui.py # foto da janela inteira
    $env:SMOKE_REAL='1';     python tools/smoke_gui.py # janela real na tela

Variáveis de ambiente:

* ``SMOKE_THEME``  — ``light`` ou ``dark``; sem ela, segue o tema do Windows.
* ``SMOKE_WINDOW`` — ``1`` fotografa a janela completa em vez de só o preview.
* ``SMOKE_REAL``   — ``1`` usa a plataforma nativa (a janela aparece). É
  obrigatório para capturas fiéis: no modo ``offscreen`` o Qt não encontra as
  fontes do sistema e o texto sai como caixas.

Sai com código 0 apenas quando todas as verificações passam e nenhum erro de
JavaScript foi registrado.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

# SMOKE_REAL=1 roda na plataforma nativa do Windows (janela aparece na tela).
# É o único modo em que as fontes e o compositor do Chromium são os reais, o
# que importa para gerar capturas fiéis para a documentação.
if os.environ.get("SMOKE_REAL") == "1":
    os.environ.pop("QT_QPA_PLATFORM", None)
    os.environ.pop("QTWEBENGINE_CHROMIUM_FLAGS", None)
    os.environ.pop("QT_OPENGL", None)
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # O plugin "offscreen" do Qt não oferece contexto OpenGL real, e o
    # compositor GPU do Chromium derruba o processo ao perdê-lo. Rasterização
    # por software (SwiftShader) resolve, e é o caminho suportado para
    # execução headless.
    os.environ.setdefault(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--disable-gpu --no-sandbox --enable-unsafe-swiftshader "
        "--disable-dev-shm-usage --disable-features=Vulkan",
    )
    os.environ.setdefault("QT_OPENGL", "software")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PyQt6 import QtWebEngineWidgets  # noqa: F401,E402  (antes do QApplication)
from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from edgemd.config import AppConfig  # noqa: E402
from edgemd.render import MarkdownRenderer  # noqa: E402
from edgemd.window import MainWindow  # noqa: E402

DEMO = ROOT / "docs-exemplo" / "demo.md"

#: Pasta das capturas geradas (fora do controle de versão).
OUTPUT = ROOT / "scratch"

#: Onde a documentação lê as fotos da janela.
DOCS = ROOT / "docs-exemplo"

#: JS que inspeciona o DOM renderizado.
PROBE = """
JSON.stringify({
  dataLines: document.querySelectorAll('[data-line]').length,
  headings: document.querySelectorAll('h1,h2,h3').length,
  tables: document.querySelectorAll('table').length,
  wrappedTables: document.querySelectorAll('.table-wrap').length,
  codeBlocks: document.querySelectorAll('.code-block').length,
  copyButtons: document.querySelectorAll('[data-copy]').length,
  taskItems: document.querySelectorAll('li.task-list-item').length,
  disabledBoxes: document.querySelectorAll('li.task-list-item input[disabled]').length,
  mermaidBlocks: document.querySelectorAll('.diagram-block').length,
  mermaidRendered: document.querySelectorAll('.diagram-block.is-rendered').length,
  mermaidError: document.querySelectorAll('.diagram-block.is-error').length,
  mermaidSvgs: document.querySelectorAll('.diagram-block svg').length,
  mathNodes: document.querySelectorAll('.math').length,
  katexRendered: document.querySelectorAll('.katex').length,
  images: document.querySelectorAll('img').length,
  imagesLoaded: Array.from(document.querySelectorAll('img'))
      .filter(function (i) { return i.complete && i.naturalWidth > 0; }).length,
  footnotes: document.querySelectorAll('.footnotes').length,
  anchors: document.querySelectorAll('[id]').length,
  progressBar: document.querySelectorAll('.progress-bar').length,
  themeSheetDisabled: Array.from(document.querySelectorAll('style[data-theme-sheet]'))
      .filter(function (s) { return s.disabled; })
      .map(function (s) { return s.getAttribute('data-theme-sheet'); }),
  theme: document.documentElement.getAttribute('data-theme'),
  bodyHeight: document.body.scrollHeight
})
"""


def _fresh_settings() -> Path:
    """Caminho de uma config nova a cada execução.

    O arquivo anterior é apagado em vez de reaproveitado: a geometria salva
    nele seria restaurada e mudaria o tamanho das capturas, fazendo duas
    execuções seguidas produzirem imagens diferentes.
    """
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "smoke-settings.ini"
    path.unlink(missing_ok=True)
    return path


class JsErrorCollector(logging.Handler):
    """Captura os erros de JavaScript que o PreviewPage manda para o log.

    Vale como teste de regressão: um erro de JS não derruba o app nem aparece
    no DOM, mas quebra funcionalidades em silêncio (foi assim que um bug de
    sincronia de rolagem passou despercebido).
    """

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if "JavaScript" in record.getMessage():
            self.messages.append(record.getMessage())


class Smoke:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.failures: list[str] = []
        self.js_errors = JsErrorCollector()
        logging.getLogger().addHandler(self.js_errors)
        self.window = MainWindow(
            # Config isolada e sempre nova: o teste não pode gravar nas
            # preferências reais do usuário, e reaproveitar o arquivo faria a
            # geometria salva na execução anterior mudar o tamanho das
            # capturas — duas execuções seguidas dariam imagens diferentes.
            AppConfig(settings_path=_fresh_settings()),
            MarkdownRenderer(),
        )
        self.window.resize(1400, 900)

        # Guarda o modo em que a janela nasceu, antes de o teste mexer nele:
        # é esse valor que prova que o padrão é leitura.
        self.initial_mode = self.window._view_mode
        self.window.set_view_mode("preview")

        # SMOKE_THEME permite verificar os dois temas; sem ele, vale o padrão
        # do app (seguir o Windows).
        forced = os.environ.get("SMOKE_THEME", "")
        self.theme = forced if forced in ("light", "dark") else "sistema"
        if forced in ("light", "dark"):
            self.window.config.theme_follows_system = False
            self.window.set_theme(forced)

        # SMOKE_WINDOW=1 fotografa a janela inteira (sidebar + editor +
        # preview), que é a captura representativa para o README.
        self.whole_window = os.environ.get("SMOKE_WINDOW") == "1"
        if self.whole_window:
            self.window.sidebar.set_root(str(ROOT / "docs-exemplo"))
            # O estado padrão é leitura; é ele que a documentação mostra.
            self.window.set_view_mode("preview")

        # SMOKE_EDIT=1 captura também o modo de edição, para conferir a faixa
        # com o botão "Concluir".
        self.capture_edit = os.environ.get("SMOKE_EDIT") == "1"
        # SMOKE_FIND=1 abre a busca com um termo e captura, para conferir o
        # destaque das ocorrências nos dois temas.
        self.capture_find = os.environ.get("SMOKE_FIND") == "1"

        self.shot = OUTPUT / f"preview-{self.theme}.png"
        self.shot_full = OUTPUT / f"preview-{self.theme}-completo.png"
        OUTPUT.mkdir(parents=True, exist_ok=True)

        self.window.show()

    def capture_window(self, suffix: str = "") -> None:
        """Foto da janela completa.

        Com ``SMOKE_REAL=1`` a foto é fiel e vai também para ``docs-exemplo``,
        de onde o README a lê. Em modo offscreen o Qt não acha as fontes do
        sistema, então a imagem sai com o texto em caixas — por isso ela fica
        só na pasta de rascunho nesse caso.
        """
        pixmap = self.window.grab()
        if pixmap.isNull():
            self.failures.append("grab() da janela retornou vazio")
            return

        name = f"{self.theme}{suffix}"
        destinations = [OUTPUT / f"janela-{name}.png"]
        if os.environ.get("SMOKE_REAL") == "1":
            destinations.append(DOCS / f"captura-{name}.png")

        for target in destinations:
            target.parent.mkdir(parents=True, exist_ok=True)
            pixmap.save(str(target), "PNG")
            print(f"captura da janela: {target} ({pixmap.width()}x{pixmap.height()})")

    def check_reading_default(self) -> None:
        """Confere o requisito: abre lendo, com o caminho para editar à vista."""
        window = self.window
        print("\n=== modo de leitura (padrão) ===")
        print(f"  modo inicial (sem tocar em nada) : {window._view_mode}")

        # O modo inicial é lido antes de qualquer set_view_mode do teste.
        if self.initial_mode != "preview":
            self.failures.append(
                f"o app deveria abrir em leitura, mas abriu em {self.initial_mode!r}"
            )

        if not window.mode_bar.isVisible():
            self.failures.append("a faixa de modo não está visível em leitura")
        if window.preview.isVisible() is False:
            self.failures.append("o preview não está visível em leitura")
        if window.tabs.isVisible():
            self.failures.append("o editor não deveria aparecer no modo de leitura")

        texto = window.mode_bar._button.text()
        print(f"  botão da faixa                   : {texto!r}")
        if texto != "Editar":
            self.failures.append(f"o botão de edição deveria dizer 'Editar', não {texto!r}")

        # O clique leva mesmo ao editor?
        window.mode_bar._button.click()
        depois = window._view_mode
        print(f"  modo após clicar em 'Editar'     : {depois}")
        if depois == "preview":
            self.failures.append("clicar em 'Editar' não saiu do modo de leitura")
        if not window.tabs.isVisible():
            self.failures.append("o editor não apareceu após clicar em 'Editar'")

        # E a volta?
        window.mode_bar._button.click()
        print(f"  modo após clicar em 'Concluir'   : {window._view_mode}")
        if window._view_mode != "preview":
            self.failures.append("clicar em 'Concluir' não voltou para a leitura")

    def open_search_capture(self) -> None:
        """Entra na edição, abre a busca e confere os destaques.

        Além de gerar a captura, verifica que a busca realmente marcou
        ocorrências no editor — a captura sozinha não provaria que o destaque
        existe, já que ele é desenhado pelo Qt e não aparece no DOM.
        """
        window = self.window
        window.set_view_mode("editor")
        window.open_replace()

        tab = window.current_tab
        if tab is None:
            self.failures.append("nenhuma aba aberta para buscar")
            self.done()
            return

        termo = "Mermaid"
        tab.find_bar.search_input.setText(termo)
        tab.search._on_search_changed(termo, tab.find_bar.options)

        encontradas = len(tab.search.matches)
        destacadas = len(tab.editor._search_ranges)
        print("\n=== busca no editor ===")
        print(f"  termo            : {termo!r}")
        print(f"  ocorrencias      : {encontradas}")
        print(f"  destacadas       : {destacadas}")
        print(f"  contador da barra: {tab.find_bar.count_label.text()!r}")
        print(f"  barra visivel    : {tab.find_bar.isVisible()}")

        if encontradas == 0:
            self.failures.append("a busca não encontrou nenhuma ocorrência")
        if destacadas != encontradas:
            self.failures.append(
                f"destacou {destacadas} de {encontradas} ocorrências"
            )
        if not tab.find_bar.isVisible():
            self.failures.append("a barra de busca não ficou visível")

        QTimer.singleShot(600, self.capture_find_mode)

    def capture_find_mode(self) -> None:
        self.capture_window("-busca")
        self.done()

    def capture_edit_mode(self) -> None:
        self.capture_window("-edicao")
        self.done()

    def run(self) -> int:
        self.window.open_paths([str(DEMO)])
        # Mermaid é um bundle de 3,5 MB e o KaTeX desenha depois: sem esta
        # espera, o teste mediria o estado intermediário.
        QTimer.singleShot(6500, self.probe)
        self.app.exec()
        return self.report()

    def probe(self) -> None:
        page = self.window.preview.page()
        page.runJavaScript(PROBE, self.check)

    def check(self, raw) -> None:
        try:
            data = json.loads(raw) if isinstance(raw, str) else {}
        except (TypeError, ValueError):
            data = {}

        print("\n=== DOM renderizado ===")
        for key, value in data.items():
            print(f"  {key:22} {value}")

        def expect(key: str, minimum: int) -> None:
            got = data.get(key, 0)
            if not isinstance(got, int) or got < minimum:
                self.failures.append(f"{key}: esperado >= {minimum}, obtido {got}")

        expect("dataLines", 40)
        expect("headings", 8)
        expect("tables", 1)
        expect("wrappedTables", 1)
        expect("codeBlocks", 4)
        expect("copyButtons", 4)
        expect("taskItems", 3)
        expect("disabledBoxes", 3)
        expect("mermaidBlocks", 2)
        expect("mermaidRendered", 2)
        expect("mermaidSvgs", 2)
        # O demo.md tem 7 fórmulas: 2 inline no parágrafo, 2 em bloco, e 3 de
        # sub/sobrescrito. Contar 9 seria erro do teste, não do renderer.
        expect("mathNodes", 7)
        expect("katexRendered", 7)
        expect("images", 1)
        expect("imagesLoaded", 1)
        expect("footnotes", 1)
        expect("progressBar", 1)

        if data.get("mermaidError", 0):
            self.failures.append(f"{data['mermaidError']} diagrama(s) Mermaid com erro")

        # O tema inicial segue o Windows (config padrão). Conferimos apenas que
        # a folha do outro tema ficou desabilitada, que é o invariante real.
        theme = data.get("theme")
        if theme not in ("light", "dark"):
            self.failures.append(f"tema inválido: {theme!r}")
        if data.get("themeSheetDisabled") != [("light" if theme == "dark" else "dark")]:
            self.failures.append(
                f"folha de estilo incoerente com o tema {theme!r}: "
                f"{data.get('themeSheetDisabled')}"
            )

        self.grab()

    def grab(self) -> None:
        view = self.window.preview
        pixmap = view.grab()
        if pixmap.isNull():
            self.failures.append("grab() do preview retornou vazio")
        else:
            pixmap.save(str(self.shot), "PNG")
            print(f"\nfoto do preview: {self.shot} ({pixmap.width()}x{pixmap.height()})")

        if self.whole_window:
            # Verifica o requisito central: o app abre lendo, e o componente de
            # edição está visível e clicável.
            self.check_reading_default()
            self.capture_window()
            if self.capture_find:
                self.open_search_capture()
                return
            if self.capture_edit:
                self.window.enter_edit_mode()
                QTimer.singleShot(700, self.capture_edit_mode)
                return
            self.done()
            return

        # Segunda foto com a página inteira, para conferir o que está abaixo
        # da dobra (tabelas, código, diagramas, fórmulas).
        view.page().runJavaScript(
            "document.body.scrollHeight", self.after_height
        )

    def after_height(self, height) -> None:
        try:
            total = int(height)
        except (TypeError, ValueError):
            total = 0
        if total <= 0:
            self.done()
            return
        self._total_height = total
        self._offset = 0
        self._shots: list = []
        self.scroll_step()

    def scroll_step(self) -> None:
        view = self.window.preview
        view.page().runJavaScript(
            f"window.scrollTo(0, {self._offset}); "
            "(function(){var b=document.querySelector('.progress-bar');"
            "return b?b.style.width:'0%';})()",
            self.on_scrolled,
        )

    def on_scrolled(self, _progress) -> None:
        view = self.window.preview
        QTimer.singleShot(700, lambda: self.capture_slice(view))

    def capture_slice(self, view) -> None:
        pixmap = view.grab()
        height = view.height()
        if not pixmap.isNull():
            self._shots.append(pixmap)
        self._offset += height - 40
        if self._offset < self._total_height and len(self._shots) < 6:
            self.scroll_step()
        else:
            self.stitch()

    def stitch(self) -> None:
        """Empilha as fatias numa imagem só, para inspeção visual."""
        from PyQt6.QtGui import QPainter, QPixmap

        if not self._shots:
            self.done()
            return

        width = max(p.width() for p in self._shots)
        total = sum(p.height() for p in self._shots)
        combined = QPixmap(width, total)
        combined.fill()
        painter = QPainter(combined)
        y = 0
        for pixmap in self._shots:
            painter.drawPixmap(0, y, pixmap)
            y += pixmap.height()
        painter.end()

        combined.save(str(self.shot_full), "PNG")
        print(f"foto completa    : {self.shot_full} ({combined.width()}x{combined.height()})")
        self.done()

    def done(self) -> None:
        self.app.quit()

    def report(self) -> int:
        # Um erro de JS não derruba o app nem aparece no DOM, mas quebra
        # funcionalidades em silêncio — por isso conta como falha do teste.
        for message in self.js_errors.messages:
            self.failures.append(f"erro de JS: {message}")

        print()
        if self.failures:
            print("PROBLEMAS:")
            for item in self.failures:
                print("  -", item)
            return 1
        print("GUI SMOKE OK")
        return 0


if __name__ == "__main__":
    app = QApplication(sys.argv)
    raise SystemExit(Smoke(app).run())
