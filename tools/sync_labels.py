"""Aplica .github/labels.yml no repositório via gh (cria ou atualiza, nunca apaga)."""
import re
import subprocess
import sys
from pathlib import Path

REPO = "EduradoPessoa/edge-md"
LINHA = re.compile(r'- \{name: (?P<n>[^,]+), color: (?P<c>\w+), description: "(?P<d>[^"]*)"\}')


def main() -> int:
    texto = (Path(__file__).parent.parent / ".github" / "labels.yml").read_text(encoding="utf-8")
    rotulos = [m.groupdict() for m in map(LINHA.match, texto.splitlines()) if m]
    if not rotulos:
        print("nenhum rótulo lido", file=sys.stderr)
        return 1
    for r in rotulos:
        subprocess.run(["gh", "label", "create", r["n"], "-R", REPO, "--color", r["c"],
                        "--description", r["d"], "--force"], check=True, capture_output=True)
        print("ok:", r["n"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
