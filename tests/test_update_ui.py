"""Os diálogos de atualização montam sem rede e refletem o estado das versões."""

from __future__ import annotations

from edgemd import __version__
from edgemd.update_ui import UpdateDialog, VersionsDialog
from edgemd.updater import Asset, Release

BASE = "https://github.com/EduradoPessoa/edge-md/releases/download"


def _rel(version: str, instalavel: bool = True) -> Release:
    nome = f"EdgeMD-{version}-setup.exe"
    assets = {}
    if instalavel:
        assets = {nome: Asset(nome, f"{BASE}/v{version}/{nome}"),
                  "SHA256SUMS.txt": Asset("SHA256SUMS.txt", f"{BASE}/v{version}/SHA256SUMS.txt")}
    return Release(f"v{version}", version, version, "notas", "https://x", "2026-01-02T00:00:00Z", False, assets)


def test_dialogo_de_versoes_marca_a_situacao(qapp):
    rels = [_rel("9.0.0"), _rel(__version__), _rel("0.0.1", instalavel=False)]
    d = VersionsDialog(rels, can_install=True)
    col = [d.table.item(i, 2).text() for i in range(3)]
    assert col[0].startswith("mais nova")
    assert col[1].startswith("em uso")
    assert "sem instalador" in col[2]


def test_versao_em_uso_nao_pode_ser_instalada(qapp):
    d = VersionsDialog([_rel(__version__), _rel("9.0.0")], can_install=True)
    d.table.selectRow(0)
    assert not d.install_btn.isEnabled()
    d.table.selectRow(1)
    assert d.install_btn.isEnabled()


def test_sem_auto_instalacao_o_botao_fica_desligado(qapp):
    d = VersionsDialog([_rel("9.0.0")], can_install=False)
    assert not d.install_btn.isEnabled()


def test_dialogo_de_atualizacao_escolhas(qapp):
    d = UpdateDialog(_rel("9.0.0"), can_install=True)
    assert d.choice == UpdateDialog.LATER
