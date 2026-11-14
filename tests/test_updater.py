"""Testes da atualização: tudo sem rede, com um opener falso."""

from __future__ import annotations

import hashlib
import io
import json

import pytest

from edgemd import updater
from edgemd.updater import (
    Asset,
    Cancelled,
    ChecksumError,
    Release,
    UpdateError,
    download_installer,
    is_newer,
    newest_update,
    parse_releases,
    parse_sums,
    parse_version,
    prune_cache,
    should_check,
)

BASE = f"https://github.com/{updater.REPO}/releases/download"
CONTEUDO = b"instalador-falso" * 1000
HASH = hashlib.sha256(CONTEUDO).hexdigest()


class FakeResp(io.BytesIO):
    def __init__(self, data: bytes, url: str = "", headers: dict | None = None):
        super().__init__(data)
        self._url = url
        self.headers = headers or {}

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def opener_de(mapa: dict[str, bytes], final: str | None = None):
    """Devolve um opener que atende por URL, e registra o que foi pedido."""
    pedidos: list[str] = []

    def abrir(req, timeout=None):
        url = req.full_url
        pedidos.append(url)
        if url not in mapa:
            raise OSError(f"sem rota: {url}")
        return FakeResp(mapa[url], final or url)

    abrir.pedidos = pedidos  # type: ignore[attr-defined]
    return abrir


def release(version="0.2.0", com_sums=True, installer_url=None) -> Release:
    nome = f"EdgeMD-{version}-setup.exe"
    assets = {nome: Asset(nome, installer_url or f"{BASE}/v{version}/{nome}", len(CONTEUDO))}
    if com_sums:
        assets["SHA256SUMS.txt"] = Asset("SHA256SUMS.txt", f"{BASE}/v{version}/SHA256SUMS.txt")
    return Release(f"v{version}", version, f"v{version}", "notas", "https://x", "2026-01-02T00:00:00Z", False, assets)


def sums_de(version="0.2.0", h=HASH) -> bytes:
    return f"{h}  EdgeMD-{version}-setup.exe\n".encode()


# -- versões ---------------------------------------------------------------
@pytest.mark.parametrize(
    "novo,atual,esperado",
    [
        ("0.2.0", "0.1.0", True),
        ("v0.10.0", "0.9.0", True),  # comparação numérica, não de texto
        ("1.0.0", "1.0.0", False),
        ("0.1.0", "0.2.0", False),
        ("1.0.0", "1.0.0-rc1", True),  # final vence pré-lançamento
        ("1.0.0-rc1", "1.0.0", False),
        ("lixo", "0.1.0", False),
    ],
)
def test_is_newer(novo, atual, esperado):
    assert is_newer(novo, atual) is esperado


def test_parse_version_rejeita_nao_semver():
    assert parse_version("1.2") is None
    assert parse_version("") is None


# -- releases --------------------------------------------------------------
def _item(tag, **kw):
    base = {"tag_name": tag, "name": tag, "body": "b", "html_url": "u", "published_at": "2026-01-01T00:00:00Z",
            "draft": False, "prerelease": False, "assets": []}
    base.update(kw)
    return base


def test_parse_releases_ordena_e_filtra():
    out = parse_releases([
        _item("v0.2.0"), _item("v0.10.0"), _item("v0.3.0", draft=True),
        _item("v0.4.0", prerelease=True), _item("nightly"),
    ])
    assert [r.version for r in out] == ["0.10.0", "0.2.0"]


def test_parse_releases_inclui_prerelease_quando_pedido():
    out = parse_releases([_item("v0.4.0-rc1", prerelease=True)], include_prereleases=True)
    assert [r.version for r in out] == ["0.4.0-rc1"]


def test_fetch_releases_usa_a_api_e_converte():
    payload = json.dumps([_item("v0.2.0")]).encode()
    op = opener_de({updater.RELEASES_API: payload})
    assert [r.version for r in updater.fetch_releases(opener=op)] == ["0.2.0"]


def test_fetch_releases_erro_de_rede_vira_updateerror():
    with pytest.raises(UpdateError):
        updater.fetch_releases(opener=opener_de({}))


def test_newest_update():
    rels = [release("0.3.0"), release("0.2.0")]
    assert newest_update(rels, "0.2.0").version == "0.3.0"
    assert newest_update(rels, "0.3.0") is None
    assert newest_update([], "0.1.0") is None


def test_installable_exige_checksum():
    assert release().installable
    assert not release(com_sums=False).installable


# -- checksums -------------------------------------------------------------
def test_parse_sums_aceita_asterisco_e_ignora_lixo():
    h = "a" * 64
    assert parse_sums(f"{h} *x.exe\nlinha ruim\n{h.upper()}  y.deb") == {"x.exe": h, "y.deb": h}


# -- download --------------------------------------------------------------
def _mapa(version="0.2.0", conteudo=CONTEUDO, h=HASH):
    r = release(version)
    return r, {r.installer.url: conteudo, r.sums.url: sums_de(version, h)}


def test_download_confere_e_grava(tmp_path):
    r, mapa = _mapa()
    progresso = []
    destino = download_installer(r, root=tmp_path, opener=opener_de(mapa), progress=lambda a, b: progresso.append(a))
    assert destino.read_bytes() == CONTEUDO
    assert progresso and progresso[-1] == len(CONTEUDO)
    assert not list(tmp_path.rglob("*.part"))


def test_download_com_hash_errado_apaga_tudo(tmp_path):
    r, mapa = _mapa(conteudo=CONTEUDO + b"corrompido")
    with pytest.raises(ChecksumError):
        download_installer(r, root=tmp_path, opener=opener_de(mapa))
    assert not list(tmp_path.rglob("*.exe")) and not list(tmp_path.rglob("*.part"))


def test_download_reaproveita_cache_valido(tmp_path):
    r, mapa = _mapa()
    op = opener_de(mapa)
    download_installer(r, root=tmp_path, opener=op)
    op.pedidos.clear()
    download_installer(r, root=tmp_path, opener=op)
    assert r.installer.url not in op.pedidos  # só o checksum foi consultado


def test_download_refaz_cache_adulterado(tmp_path):
    r, mapa = _mapa()
    caminho = download_installer(r, root=tmp_path, opener=opener_de(mapa))
    caminho.write_bytes(b"adulterado")
    assert download_installer(r, root=tmp_path, opener=opener_de(mapa)).read_bytes() == CONTEUDO


def test_download_recusa_url_fora_do_repositorio(tmp_path):
    r = release(installer_url="https://evil.example/EdgeMD-0.2.0-setup.exe")
    with pytest.raises(UpdateError):
        download_installer(r, root=tmp_path, opener=opener_de({}))


def test_download_recusa_redirecionamento_para_host_estranho(tmp_path):
    r, mapa = _mapa()
    with pytest.raises(UpdateError):
        download_installer(r, root=tmp_path, opener=opener_de(mapa, final="https://evil.example/x"))


def test_download_sem_linha_no_sums(tmp_path):
    r, mapa = _mapa()
    mapa[r.sums.url] = b"e" * 64 + b"  outro.exe\n"
    with pytest.raises(UpdateError):
        download_installer(r, root=tmp_path, opener=opener_de(mapa))


def test_download_cancelado_nao_deixa_resto(tmp_path):
    r, mapa = _mapa()
    with pytest.raises(Cancelled):
        download_installer(r, root=tmp_path, opener=opener_de(mapa), cancelled=lambda: True)
    assert not list(tmp_path.rglob("*.part"))


# -- cache e rollback ------------------------------------------------------
def test_prune_cache_mantem_atual_e_anterior(tmp_path):
    for v in ("0.1.0", "0.2.0", "0.3.0"):
        (tmp_path / v).mkdir()
    removidas = prune_cache(["0.3.0", "0.2.0"], root=tmp_path)
    assert removidas == ["0.1.0"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["0.2.0", "0.3.0"]


def test_cached_installer(tmp_path):
    r = release()
    assert updater.cached_installer(r, tmp_path) is None
    (tmp_path / "0.2.0").mkdir()
    (tmp_path / "0.2.0" / r.installer.name).write_bytes(b"x")
    assert updater.cached_installer(r, tmp_path) is not None


def test_argumentos_do_instalador_tem_relaunch_e_silent():
    args = updater.installer_arguments()
    assert "/SILENT" in args and "/RELAUNCH" in args and "/CLOSEAPPLICATIONS" in args


def test_nome_de_instalador_so_aceita_o_padrao():
    assert updater.INSTALLER_RE.match("EdgeMD-0.2.0-setup.exe")
    assert not updater.INSTALLER_RE.match("..\\EdgeMD-0.2.0-setup.exe")
    assert not updater.INSTALLER_RE.match("malware.exe")


def test_nao_instala_sozinho_fora_do_exe_instalado():
    assert updater.can_self_install() is False  # rodando do código-fonte


def test_should_check():
    assert should_check(0, now=updater.CHECK_INTERVAL_SECONDS)
    assert not should_check(100, now=101)


# -- reportar problema -----------------------------------------------------
def test_url_de_reporte_leva_so_versao_e_sistema():
    from urllib.parse import parse_qs, urlparse

    url = updater.report_problem_url()
    q = parse_qs(urlparse(url).query)
    assert urlparse(url).path == f"/{updater.REPO}/issues/new"
    assert q["template"] == ["bug.yml"]
    assert q["versao"] == [updater.__version__]
    assert q["sistema"][0] in {"Windows 10", "Windows 11", "Linux", "macOS", "Outro"}
    assert set(q) <= {"template", "versao", "sistema", "instalacao"}


def test_campos_do_url_existem_no_formulario():
    """Se alguém renomear um id no bug.yml, o preenchimento some em silêncio."""
    from pathlib import Path

    texto = (Path(__file__).resolve().parent.parent / ".github" / "ISSUE_TEMPLATE" / "bug.yml").read_text(encoding="utf-8")
    for campo in ("versao", "sistema", "instalacao"):
        assert f"id: {campo}" in texto
