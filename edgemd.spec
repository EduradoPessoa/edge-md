# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller para gerar ``dist\\edgemd.exe``.

Uso:
    python -m pip install pyinstaller
    pyinstaller edgemd.spec --noconfirm --clean

Sobre os dados: o destino de cada ``datas`` precisa casar com
``edgemd.paths.asset_path``/``icon_path`` no modo congelado, que procuram em
``sys._MEIPASS/render/assets`` e ``sys._MEIPASS/resources/icons``. Mudar o
destino aqui sem mudar lá faz o app subir sem CSS e sem ícone.

Sobre ``--windowed``: sem console. É o que a associação de arquivo precisa,
senão uma janela preta pisca a cada clique duplo num .md.

O ``mermaid.min.js`` tem ~3,5 MB e as fontes do KaTeX somam ~1 MB; o exe final
fica na casa das centenas de MB, quase tudo Qt WebEngine (o Chromium embutido).
Não há como reduzir isso mantendo a renderização por Chromium.
"""

from pathlib import Path

# O spec é executado pelo PyInstaller com o diretório do spec como cwd, mas
# usamos caminhos absolutos para não depender disso.
ROOT = Path(SPECPATH).resolve()

datas = [
    # CSS, JS do preview, fontes do KaTeX e bundles de Mermaid/KaTeX.
    (str(ROOT / "src" / "edgemd" / "render" / "assets"), "render/assets"),
    # Ícone usado na janela, na bandeja e no registro de associação.
    (str(ROOT / "src" / "edgemd" / "resources" / "icons"), "resources/icons"),
]

hiddenimports = [
    # O Qt carrega estes módulos dinamicamente; sem declará-los, o preview
    # sobe em branco no executável.
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebChannel",
    "PyQt6.QtNetwork",
    "PyQt6.QtPrintSupport",
    # Plugins de Markdown, carregados por nome dentro de build_parser().
    "mdit_py_plugins.tasklists",
    "mdit_py_plugins.footnote",
    "mdit_py_plugins.deflist",
    "mdit_py_plugins.anchors",
    "mdit_py_plugins.dollarmath",
    # Lexers do Pygments são resolvidos em tempo de execução por nome.
    "pygments.lexers",
    "pygments.formatters",
    "pygments.styles",
]

# Exclui o que não é usado e só engorda o bundle.
excludes = [
    "tkinter",
    "unittest",
    "pydoc_data",
    "PyQt6.QtQml",
    "PyQt6.QtQuick",
    "PyQt6.QtQuick3D",
    "PyQt6.QtBluetooth",
    "PyQt6.QtMultimedia",
    "PyQt6.QtSql",
    "PyQt6.QtTest",
    "PyQt6.QtDesigner",
    "PyQt6.QtHelp",
]

a = Analysis(
    [str(ROOT / "run.pyw")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="edgemd",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # --windowed: sem janela de console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "src" / "edgemd" / "resources" / "icons" / "edgemd.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="edgemd",
)
