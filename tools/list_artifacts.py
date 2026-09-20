"""Lista os artefatos da execucao da matriz de release."""
from __future__ import annotations

import json
import subprocess
import sys

RUN = sys.argv[1] if len(sys.argv) > 1 else "35449448626"

saida = subprocess.run(
    ["gh", "api", f"repos/EduradoPessoa/edge-md/actions/runs/{RUN}/artifacts"],
    capture_output=True, check=False,
)
if saida.returncode != 0:
    print("  FALHA:", saida.stderr.decode("utf-8", "replace")[:200])
    raise SystemExit(1)

d = json.loads(saida.stdout.decode("utf-8-sig"))
artefatos = d.get("artifacts", [])
for a in artefatos:
    print(f"  {a['name']:<26} {a['size_in_bytes'] / 1048576:6.1f} MB   "
          f"expira {a['expires_at'][:10]}")
print(f"  total: {len(artefatos)} artefatos")
