"""Configuração compartilhada dos testes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edgemd.render import MarkdownRenderer  # noqa: E402


@pytest.fixture(scope="session")
def renderer() -> MarkdownRenderer:
    """Um renderer por sessão: montar o parser é caro e ele é imutável."""
    return MarkdownRenderer()


@pytest.fixture
def md_file(tmp_path: Path):
    """Cria um .md temporário e devolve seu caminho."""

    def create(text: str, name: str = "nota.md", *, encoding: str = "utf-8", eol: str = "\n") -> Path:
        path = tmp_path / name
        payload = text.replace("\n", eol).encode(encoding)
        path.write_bytes(payload)
        return path

    return create
