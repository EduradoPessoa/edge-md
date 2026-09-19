"""Baixa as bibliotecas de terceiros usadas pelo preview (Mermaid e KaTeX).

O app precisa funcionar offline, então nada de CDN em tempo de execução: os
arquivos ficam versionados localmente em ``render/assets/vendor``.

Decisões:

* **Mermaid fica na linha 11.** A 12 é recente e o ``preview.js`` usa a API
  ``mermaid.render(id, code)`` que devolve Promise, consolidada na v10/v11.
  Trocar de major aqui exige revisar aquele código — por isso o script recusa
  resolver para outra major sem ``--mermaid-major``.
* **As fontes do KaTeX são descobertas a partir do próprio CSS**, em vez de
  uma lista fixa. Se uma versão nova passar a referenciar outra fonte, o
  download acompanha sozinho.
* **O manifesto registra versão e sha256** de cada arquivo, para que dê para
  auditar depois o que exatamente está empacotado.

Uso:
    python tools/fetch_vendor.py
    python tools/fetch_vendor.py --force        # rebaixa tudo
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

VENDOR = (
    Path(__file__).resolve().parent.parent
    / "src" / "edgemd" / "render" / "assets" / "vendor"
)

NPM_REGISTRY = "https://registry.npmjs.org/{pkg}"
JSDELIVR = "https://cdn.jsdelivr.net/npm/{pkg}@{version}/{path}"

#: Mermaid: major fixada de propósito (ver docstring).
MERMAID_MAJOR = 11
#: KaTeX: qualquer 0.x recente serve; a API katex.render é estável.
KATEX_MAJOR = 0

USER_AGENT = "edgemd-fetch-vendor/1.0 (+https://localhost)"

#: (origem dentro do pacote npm, destino relativo em vendor/)
#:
#: O ``contrib/auto-render`` do KaTeX fica de fora de propósito. Ele varre o
#: DOM inteiro procurando delimitadores ``$``, o que transformaria texto comum
#: como "custa $5 e $10" em fórmula. Usamos ``katex.render`` direto nos
#: elementos que o plugin dollarmath gerou — que já passaram por um parser de
#: verdade — então o auto-render seria peso morto com efeito colateral.
FILES = [
    ("mermaid", "dist/mermaid.min.js", "mermaid.min.js"),
    ("katex", "dist/katex.min.js", "katex/katex.min.js"),
    ("katex", "dist/katex.min.css", "katex/katex.min.css"),
]

#: O CSS do KaTeX aponta para as fontes com caminho relativo (``fonts/...``).
FONT_URL = re.compile(r"url\(\s*['\"]?(fonts/[^'\")]+)['\"]?\s*\)")


# --------------------------------------------------------------------------
# Rede
# --------------------------------------------------------------------------

def fetch(url: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def resolve_version(package: str, major: int | None) -> str:
    """Versão mais recente do pacote, opcionalmente travada numa major."""
    data = json.loads(fetch(NPM_REGISTRY.format(pkg=package), timeout=45).decode("utf-8"))
    if major is None:
        return data["dist-tags"]["latest"]

    candidates: list[tuple[int, int, int, str]] = []
    for version in data.get("versions", {}):
        parts = version.split("-")[0].split(".")  # ignora pré-lançamentos
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            continue
        nums = tuple(int(p) for p in parts)
        if nums[0] == major:
            candidates.append((*nums, version))

    if not candidates:
        raise SystemExit(f"nenhuma versão {major}.x encontrada para {package}")
    candidates.sort()
    return candidates[-1][3]


# --------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------

def download(package: str, version: str, remote_path: str, target: Path, force: bool) -> dict:
    if target.exists() and not force:
        payload = target.read_bytes()
        print(f"  [pulado]  {target.relative_to(VENDOR)}  ({len(payload):,} bytes)")
    else:
        url = JSDELIVR.format(pkg=package, version=version, path=remote_path)
        try:
            payload = fetch(url)
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"falha ao baixar {url}: HTTP {exc.code}") from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        print(f"  [baixado] {target.relative_to(VENDOR)}  ({len(payload):,} bytes)")

    return {
        "package": package,
        "version": version,
        "remote": remote_path,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebaixa arquivos existentes")
    parser.add_argument("--mermaid-major", type=int, default=MERMAID_MAJOR)
    parser.add_argument("--katex-major", type=int, default=KATEX_MAJOR)
    args = parser.parse_args()

    print("Resolvendo versões...")
    versions = {
        "mermaid": resolve_version("mermaid", args.mermaid_major),
        "katex": resolve_version("katex", args.katex_major),
    }
    for name, version in versions.items():
        print(f"  {name}: {version}")

    print("\nBaixando arquivos principais...")
    manifest = [download(pkg, versions[pkg], remote, VENDOR / dest, args.force) for pkg, remote, dest in FILES]

    # Fontes do KaTeX, descobertas a partir do CSS já baixado.
    css_path = VENDOR / "katex" / "katex.min.css"
    fonts = sorted(set(FONT_URL.findall(css_path.read_text(encoding="utf-8"))))
    if not fonts:
        print("\nAVISO: nenhuma fonte referenciada no CSS do KaTeX.")
    else:
        print(f"\nBaixando {len(fonts)} fonte(s) do KaTeX...")
        for font in fonts:
            manifest.append(
                download("katex", versions["katex"], f"dist/{font}", VENDOR / "katex" / font, args.force)
            )

    manifest_path = VENDOR / "MANIFEST.json"
    manifest_path.write_text(
        json.dumps(
            {
                "note": "Gerado por tools/fetch_vendor.py. Não edite à mão.",
                "packages": versions,
                "files": manifest,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    total = sum(entry["bytes"] for entry in manifest)
    print(f"\n{len(manifest)} arquivos, {total / 1024 / 1024:.1f} MB no total.")
    print(f"Manifesto: {manifest_path}")

    # Conferência final: é isto que o renderer procura em disco.
    expected = [
        VENDOR / "mermaid.min.js",
        VENDOR / "katex" / "katex.min.js",
        VENDOR / "katex" / "katex.min.css",
    ]
    missing = [p for p in expected if not p.exists()]
    if missing:
        print("\nFALTANDO:")
        for path in missing:
            print("  -", path)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
