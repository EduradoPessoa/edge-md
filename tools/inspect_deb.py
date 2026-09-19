"""Inspeciona o .deb gerado, sem precisar do dpkg-deb.

Um .deb e um arquivo `ar` com control.tar.* e data.tar.* dentro. Ler as partes
com a biblioteca padrao confirma o que realmente foi empacotado, em vez de
confiar que o script fez o que prometia.
"""
from __future__ import annotations

import io
import lzma
import sys
import tarfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def ler_ar(dados: bytes) -> dict[str, bytes]:
    """Le um arquivo `ar` simples, como o .deb usa."""
    if not dados.startswith(b"!<arch>\n"):
        raise ValueError("não é um arquivo ar")

    partes: dict[str, bytes] = {}
    pos = 8
    while pos < len(dados):
        cabecalho = dados[pos : pos + 60]
        if len(cabecalho) < 60:
            break
        nome = cabecalho[0:16].decode().strip().rstrip("/")
        tamanho = int(cabecalho[48:58].decode().strip())
        inicio = pos + 60
        partes[nome] = dados[inicio : inicio + tamanho]
        pos = inicio + tamanho + (tamanho % 2)
    return partes


def abrir_tar(dados: bytes) -> tarfile.TarFile:
    """Abre o tar interno, seja qual for a compressão.

    O dpkg moderno usa **zstd** por padrão (``data.tar.zst``), e não gzip nem
    xz como nos pacotes mais antigos. O ``tarfile`` só ganhou suporte a zstd no
    Python 3.14, então há um caminho manual de reserva que descomprime antes.
    """
    for modo in ("r:xz", "r:gz", "r:zst", "r:"):
        try:
            return tarfile.open(fileobj=io.BytesIO(dados), mode=modo)
        except (tarfile.TarError, lzma.LZMAError, ValueError):
            continue

    # Reserva: descomprime com o módulo zstd e entrega o tar puro.
    try:
        from compression import zstd

        return tarfile.open(fileobj=io.BytesIO(zstd.decompress(dados)), mode="r:")
    except ImportError:
        pass

    raise ValueError(
        "formato de tar não reconhecido (zstd exige Python 3.14 ou o pacote zstandard)"
    )


def main() -> int:
    deb = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if deb is None or not deb.is_file():
        candidatos = list((RAIZ / "dist" / "linux").glob("*.deb"))
        candidatos += list(Path.home().glob("**/edgemd_*.deb"))
        if not candidatos:
            print("ERRO: nenhum .deb encontrado")
            return 1
        deb = candidatos[0]

    print(f"Arquivo: {deb.name} ({deb.stat().st_size / 1048576:.1f} MB)")

    partes = ler_ar(deb.read_bytes())
    print(f"Partes: {', '.join(sorted(partes))}")

    # -- control ---------------------------------------------------------
    nome_control = next((n for n in partes if n.startswith("control.tar")), None)
    if nome_control:
        print("\n=== DEBIAN/control ===")
        with abrir_tar(partes[nome_control]) as tar:
            membro = next(
                (m for m in tar.getmembers() if m.name.endswith("control")), None
            )
            if membro:
                conteudo = tar.extractfile(membro).read().decode("utf-8")
                for linha in conteudo.splitlines():
                    print(f"  {linha}")

            gatilhos = [m.name for m in tar.getmembers() if "post" in m.name]
            print(f"  gatilhos: {gatilhos}")

    # -- data ------------------------------------------------------------
    nome_data = next((n for n in partes if n.startswith("data.tar")), None)
    if not nome_data:
        print("ERRO: sem data.tar")
        return 1

    with abrir_tar(partes[nome_data]) as tar:
        nomes = tar.getnames()

        print("\n=== conteudo ===")
        executavel = [n for n in nomes if n.endswith("opt/edgemd/edgemd")]
        print(f"  executável          : {executavel[0] if executavel else 'AUSENTE'}")
        print(f"  total de arquivos   : {len(nomes)}")

        desktop = [n for n in nomes if n.endswith(".desktop")]
        print(f"  atalho .desktop     : {desktop}")

        icones = sorted(n for n in nomes if "/icons/hicolor/" in n and n.endswith(".png"))
        print(f"  ícones              : {len(icones)} tamanhos")
        for i in icones[:3]:
            print(f"      {i}")

        lancador = [n for n in nomes if n.endswith("usr/bin/edgemd")]
        print(f"  lançador em /usr/bin: {lancador}")

        # O conteudo do .desktop e o que registra a associacao no Linux.
        if desktop:
            with abrir_tar(partes[nome_data]) as tar2:
                texto = tar2.extractfile(desktop[0]).read().decode("utf-8")
            print("\n=== conteúdo do .desktop ===")
            for linha in texto.splitlines():
                if linha.strip():
                    print(f"  {linha}")

            faltando = [
                chave
                for chave in ("Exec=", "Icon=", "MimeType=", "Type=Application")
                if chave not in texto
            ]
            print()
            if faltando:
                print(f"  FALHA: faltam chaves obrigatórias: {faltando}")
                return 1
            print("  OK: o .desktop tem as chaves que registram a associação")

            if "text/markdown" not in texto:
                print("  FALHA: sem text/markdown, o Linux não oferece o app")
                return 1
            print("  OK: declara text/markdown")

    if not executavel:
        print("\n  FALHA: o executável não foi empacotado")
        return 1

    print("\n  OK: pacote íntegro")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
