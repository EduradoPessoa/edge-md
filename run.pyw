"""Entrypoint sem console para o EdgeMD.

A extensão .pyw faz o Windows rodar via pythonw.exe, sem abrir janela de
terminal. É este arquivo que a associação de arquivo chama quando você dá
clique duplo num .md.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edgemd.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
