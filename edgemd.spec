# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller do EdgeMD, para Windows, Linux e macOS.

Uso:
    python -m pip install pyinstaller Pillow
    pyinstaller edgemd.spec --noconfirm --clean

O PyInstaller **não compila para outra plataforma**: cada sistema gera o seu
artefato, e é por isso que existe o workflow de release em
``.github/workflows/release.yml``, rodando a matriz nas três. Este arquivo é o
mesmo nos três; o que muda vem de ``sys.platform``.

Sobre os dados empacotados: o destino de cada ``datas`` precisa casar com
``edgemd.paths.asset_path``/``icon_path`` no modo congelado, que procuram em
``sys._MEIPASS/render/assets`` e ``sys._MEIPASS/resources/icons``. Mudar o
destino aqui sem mudar lá faz o app subir sem CSS e sem ícone.

Sobre o tamanho: o bundle fica na casa das centenas de MB porque carrega o
Chromium inteiro. É o preço da renderização fiel, e não há como reduzir isso
mantendo o Qt WebEngine.
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve()

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

BUNDLE_ID = "io.github.eduradopessoa.edgemd"

datas = [
    # CSS, JS do preview, fontes do KaTeX e bundles de Mermaid/KaTeX.
    (str(ROOT / "src" / "edgemd" / "render" / "assets"), "render/assets"),
    # Ícones: .ico no Windows, .icns no macOS, .png no Linux.
    (str(ROOT / "src" / "edgemd" / "resources" / "icons"), "resources/icons"),
]

hiddenimports = [
    # O Qt carrega estes módulos dinamicamente; sem declará-los, o preview sobe
    # em branco no executável.
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebChannel",
    "PyQt6.QtNetwork",
    "PyQt6.QtPrintSupport",
    "PyQt6.QtSvg",
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


def platform_icon() -> str | None:
    """Ícone adequado à plataforma, ou None quando não há.

    O PyInstaller aceita ``.ico`` no Windows e ``.icns`` no macOS. No Linux o
    parâmetro é ignorado, e apontar para um arquivo inexistente daria erro — daí
    o None explícito.
    """
    icons = ROOT / "src" / "edgemd" / "resources" / "icons"
    if IS_WINDOWS:
        candidato = icons / "edgemd.ico"
    elif IS_MACOS:
        candidato = icons / "edgemd.icns"
    else:
        return None
    return str(candidato) if candidato.is_file() else None


def macos_info_plist() -> dict:
    """``Info.plist`` do bundle do macOS.

    É aqui que a associação de arquivos do macOS acontece: o LaunchServices
    monta a lista de "Abrir com" a partir do ``CFBundleDocumentTypes`` dos
    bundles instalados. Sem esta declaração o EdgeMD nunca aparece, por mais que
    o usuário procure — e nenhum código em tempo de execução resolve isso.
    """
    return {
        "CFBundleName": "EdgeMD",
        "CFBundleDisplayName": "EdgeMD",
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "edgemd",
        "CFBundleIconFile": "edgemd.icns",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Documento Markdown",
                "CFBundleTypeRole": "Editor",
                # "Owner" faz o macOS preferir o EdgeMD quando o arquivo não tem
                # outro dono declarado.
                "LSHandlerRank": "Owner",
                # A UTI canônica do Markdown, adotada por quase todos os
                # editores do sistema. "public.plain-text" cobre .txt.
                "LSItemContentTypes": [
                    "net.daringfireball.markdown",
                    "public.plain-text",
                ],
                "CFBundleTypeExtensions": ["md", "markdown", "mdown", "mkd", "mkdn"],
            }
        ],
    }


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
    # Sem console. É o que a associação de arquivo precisa: senão uma janela
    # preta pisca a cada clique duplo num .md. No Linux e no macOS o parâmetro é
    # aceito e não tem efeito.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=platform_icon(),
)

if IS_MACOS:
    # No macOS o resultado é um .app: é o bundle que carrega o Info.plist com a
    # declaração dos tipos de documento.
    app = BUNDLE(
        exe,
        a.binaries,
        a.datas,
        name="EdgeMD.app",
        icon=platform_icon(),
        bundle_identifier=BUNDLE_ID,
        info_plist=macos_info_plist(),
    )
else:
    # Windows e Linux: pasta com o executável e as dependências ao lado. O
    # instalador de cada sistema empacota essa pasta.
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="edgemd",
    )
