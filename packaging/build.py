"""Build do EdgeMD para a plataforma atual.

Uso:
    python packaging/build.py                 # só o bundle
    python packaging/build.py --instalador    # bundle + instalador do sistema

O PyInstaller não compila para outra plataforma — ele empacota o interpretador e
as bibliotecas nativas do sistema onde roda. Então este script faz o que dá para
fazer localmente, e o workflow de release
(``.github/workflows/release.yml``) roda a matriz nas três para produzir os
artefatos das três.

Os instaladores:

* **Windows** — Inno Setup, a partir de ``packaging/windows/edgemd.iss``.
* **Linux** — ``.deb`` (associação de arquivos incluída) e AppImage (portátil).
* **macOS** — ``.dmg`` com o ``.app`` dentro.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIST = RAIZ / "dist"


def executar(comando: list[str], *, descricao: str) -> bool:
    """Roda um comando mostrando o que está fazendo. Não levanta."""
    print(f"==> {descricao}")
    print(f"    {' '.join(comando)}")
    try:
        resultado = subprocess.run(comando, cwd=RAIZ, check=False)
    except FileNotFoundError:
        print(f"    não encontrado: {comando[0]}")
        return False
    if resultado.returncode != 0:
        print(f"    terminou com código {resultado.returncode}")
        return False
    return True


def verificar_dependencias() -> bool:
    """Confere o que o build precisa antes de começar.

    Falhar aqui, com mensagem clara, é melhor do que descobrir no meio de um
    empacotamento de vários minutos.
    """
    problemas: list[str] = []

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        problemas.append(
            "PyInstaller ausente. Instale com: python -m pip install pyinstaller"
        )

    try:
        import PIL  # noqa: F401
    except ImportError:
        problemas.append(
            "Pillow ausente (necessário para os ícones). "
            "Instale com: python -m pip install Pillow"
        )

    if not (RAIZ / "src" / "edgemd" / "render" / "assets" / "vendor" / "mermaid.min.js").is_file():
        problemas.append(
            "Mermaid/KaTeX não baixados. Rode: python tools/fetch_vendor.py"
        )

    if not (RAIZ / "src" / "edgemd" / "resources" / "icons" / "edgemd.ico").is_file():
        problemas.append("Ícones não gerados. Rode: python tools/make_icons.py")

    for problema in problemas:
        print(f"  FALTA: {problema}")
    return not problemas


def limpar() -> None:
    for pasta in ("build", "dist"):
        alvo = RAIZ / pasta
        if alvo.exists():
            print(f"==> Removendo {pasta}/")
            shutil.rmtree(alvo, ignore_errors=True)


def gerar_bundle() -> bool:
    return executar(
        [sys.executable, "-m", "PyInstaller", "edgemd.spec", "--noconfirm", "--clean"],
        descricao="Gerando o bundle com PyInstaller",
    )


# --------------------------------------------------------------------------
# Instaladores
# --------------------------------------------------------------------------

def instalador_windows(versao: str) -> bool:
    iscc = shutil.which("iscc") or shutil.which("ISCC")
    if iscc is None:
        # Caminho padrão da instalação do Inno Setup 6.
        for candidato in (
            Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
            Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        ):
            if candidato.is_file():
                iscc = str(candidato)
                break

    if iscc is None:
        print("  Inno Setup não encontrado; pulando o instalador .exe.")
        print("  Instale de: https://jrsoftware.org/isdl.php")
        print(f"  Depois rode: iscc {RAIZ / 'packaging' / 'windows' / 'edgemd.iss'}")
        return False

    return executar(
        [iscc, str(RAIZ / "packaging" / "windows" / "edgemd.iss")],
        descricao="Gerando o instalador com Inno Setup",
    )


def pacote_msix(versao: str) -> bool:
    """Gera e assina o pacote MSIX.

    Não entra no ``--instalador`` comum de propósito: exige o makeappx e o
    signtool do Windows SDK, que não vêm instalados, e produz um pacote que só
    instala depois de o certificado ser confiado na máquina. Quem quer MSIX
    pede por ele com ``--msix``.
    """
    script = RAIZ / "packaging" / "windows" / "build_msix.ps1"
    if not script.is_file():
        print("  build_msix.ps1 não encontrado; pulando o MSIX.")
        return False

    return executar(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(script),
            "-Versao", versao,
            "-SelfSigned",
        ],
        descricao="Gerando e assinando o pacote MSIX",
    )


def instaladores_linux(versao: str) -> bool:
    ok = executar(
        ["bash", str(RAIZ / "packaging" / "linux" / "build_deb.sh"), versao],
        descricao="Gerando o pacote .deb",
    )
    # O AppImage depende do appimagetool, que talvez não esteja disponível; a
    # falha dele não invalida o .deb.
    executar(
        ["bash", str(RAIZ / "packaging" / "linux" / "build_appimage.sh"), versao],
        descricao="Gerando o AppImage",
    )
    return ok


def instalador_macos(versao: str) -> bool:
    return executar(
        ["bash", str(RAIZ / "packaging" / "macos" / "build_dmg.sh"), versao],
        descricao="Gerando o DMG",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instalador",
        action="store_true",
        help="além do bundle, gera o instalador da plataforma atual",
    )
    parser.add_argument(
        "--msix",
        action="store_true",
        help=(
            "no Windows, gera também o pacote MSIX assinado com um certificado "
            "autoassinado (exige makeappx e signtool do Windows SDK)"
        ),
    )
    parser.add_argument(
        "--sem-limpar",
        action="store_true",
        help="aproveita o build/ e o dist/ existentes",
    )
    parser.add_argument("--versao", default="0.1.0", help="versão do pacote")
    args = parser.parse_args()

    print(f"Plataforma: {sys.platform}")
    if not verificar_dependencias():
        return 1

    if not args.sem_limpar:
        limpar()

    if not gerar_bundle():
        return 1

    resultado = DIST / ("EdgeMD.app" if sys.platform == "darwin" else "edgemd")
    print(f"\n==> Bundle em: {resultado}")

    if args.instalador:
        print()
        if sys.platform == "win32":
            instalador_windows(args.versao)
        elif sys.platform == "darwin":
            instalador_macos(args.versao)
        else:
            instaladores_linux(args.versao)

    if args.msix:
        print()
        if sys.platform != "win32":
            print("  --msix só se aplica ao Windows; ignorando.")
        else:
            pacote_msix(args.versao)

    print("\n==> Concluído. Artefatos em dist/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
