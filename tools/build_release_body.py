"""Monta o corpo da Release, igual ao que o workflow faz.

Usado para corrigir uma Release ja publicada sem precisar recompilar tudo.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TAG = sys.argv[1] if len(sys.argv) > 1 else "v0.1.0"
SAIDA = RAIZ / "corpo-release.md"


def git(*args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=RAIZ, capture_output=True, text=True, check=False
    )
    return r.stdout.strip()


notas = (RAIZ / ".github" / "RELEASE_NOTES.md").read_text(encoding="utf-8")

anterior = git("describe", "--tags", "--abbrev=0", f"{TAG}^")
if anterior:
    intervalo = f"{anterior}..{TAG}"
    titulo = f"Desde `{anterior}`:"
    # O --no-merges evita poluir com commits de merge, que nao dizem nada a
    # quem le as notas.
    commits = git("log", "--no-merges", "--pretty=- %s — %h", intervalo)
else:
    titulo = "Primeira versão publicada. Histórico completo:"
    commits = git("log", "--no-merges", "--pretty=- %s — %h", TAG)

remoto = "https://github.com/EduradoPessoa/edge-md"

corpo = (
    notas.rstrip()
    + "\n\n## Commits desta versão\n\n"
    + titulo
    + "\n\n"
    + commits
    + f"\n\n**Changelog completo**: {remoto}/commits/{TAG}\n"
)

SAIDA.write_text(corpo, encoding="utf-8")
print(f"  corpo montado: {len(corpo.splitlines())} linhas, {len(corpo)} caracteres")
print(f"  tag anterior: {anterior or '(nenhuma — primeira versão)'}")
print(f"  commits listados: {len(commits.splitlines())}")
