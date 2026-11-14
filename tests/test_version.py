"""A versão tem um único valor, replicado só onde o release-please atualiza."""
import re
from pathlib import Path

from edgemd import __version__

RAIZ = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def test_versao_e_semver():
    assert SEMVER.match(__version__)


def test_versao_igual_no_pyproject():
    # Regex em vez de tomllib: a CI também roda no Python 3.10, que não o tem.
    texto = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version = "([^"]+)"', texto, re.MULTILINE)
    assert m and m.group(1) == __version__


def test_versao_igual_no_manifesto_do_release_please():
    import json

    manifesto = json.loads((RAIZ / ".release-please-manifest.json").read_text(encoding="utf-8"))
    assert manifesto["."] == __version__


def test_versao_igual_no_instalador_inno():
    iss = (RAIZ / "packaging" / "windows" / "edgemd.iss").read_text(encoding="utf-8")
    m = re.search(r'#define AppVersion "([^"]+)"', iss)
    assert m and m.group(1) == __version__
