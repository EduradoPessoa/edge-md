"""Atualização e rollback: consulta o GitHub Releases, baixa e confere o instalador.

Este módulo não conhece o Qt. Toda a lógica que decide "há versão nova?",
"este arquivo é o certo?" e "posso instalar sozinho?" fica aqui, para ser
testada sem janela e sem rede (o ``opener`` é injetável).

Modelo de confiança, sem rodeios: o instalador é conferido contra o
``SHA256SUMS.txt`` publicado na MESMA Release. Isso protege contra download
corrompido ou truncado. Não protege contra uma Release adulterada por quem tenha
acesso à conta do projeto — só assinatura de código resolveria isso, e os
instaladores ainda não são assinados. Por isso, além do hash, o app só baixa de
endereços da própria Release deste repositório.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from edgemd import __version__
from edgemd.paths import is_frozen

log = logging.getLogger(__name__)

REPO = "EduradoPessoa/edge-md"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
ISSUES_NEW = f"https://github.com/{REPO}/issues/new/choose"

#: Os anexos só são aceitos se vierem da Release deste repositório.
_DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
#: Para onde o github.com redireciona o download de anexos.
_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}

INSTALLER_RE = re.compile(r"^EdgeMD-\d+\.\d+\.\d+[0-9A-Za-z.\-]*-setup\.exe$")
SUMS_NAME = "SHA256SUMS.txt"

MAX_API_BYTES = 4 * 1024 * 1024
MAX_INSTALLER_BYTES = 800 * 1024 * 1024
API_TIMEOUT = 8
DOWNLOAD_TIMEOUT = 30
CHECK_INTERVAL_SECONDS = 6 * 3600
#: Quantas versões ficam no cache: a instalada e a anterior (o backup local).
CACHE_KEEP = 2


class UpdateError(Exception):
    """Falha previsível do fluxo de atualização, com texto para o usuário."""


class ChecksumError(UpdateError):
    """O arquivo baixado não bate com o SHA-256 publicado."""


class Cancelled(UpdateError):
    """O usuário cancelou o download."""


# ---------------------------------------------------------------------------
# Versões
# ---------------------------------------------------------------------------
_VERSION_RE = re.compile(
    r"^v?(?P<maj>\d+)\.(?P<min>\d+)\.(?P<pat>\d+)(?:-(?P<pre>[0-9A-Za-z.\-]+))?(?:\+.*)?$"
)


def parse_version(text: str) -> tuple | None:
    """Chave ordenável de uma versão SemVer, ou None se não for uma.

    Uma versão com sufixo de pré-lançamento (``1.0.0-rc1``) vem ANTES da versão
    final igual, como manda o SemVer.
    """
    m = _VERSION_RE.match((text or "").strip())
    if not m:
        return None
    pre = m.group("pre")
    return (
        int(m.group("maj")),
        int(m.group("min")),
        int(m.group("pat")),
        0 if pre else 1,
        pre or "",
    )


def is_newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return a is not None and b is not None and a > b


def clean_version(tag: str) -> str:
    return (tag or "").strip().lstrip("vV")


# ---------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int = 0


@dataclass(frozen=True)
class Release:
    tag: str
    version: str
    name: str
    body: str
    html_url: str
    published_at: str
    prerelease: bool = False
    assets: dict[str, Asset] = field(default_factory=dict)

    @property
    def installer(self) -> Asset | None:
        """O instalador do Windows, se a Release tiver um."""
        for asset in self.assets.values():
            if INSTALLER_RE.match(asset.name):
                return asset
        return None

    @property
    def sums(self) -> Asset | None:
        return self.assets.get(SUMS_NAME)

    @property
    def installable(self) -> bool:
        """Dá para instalar sozinho: há instalador e há checksum para conferir."""
        return self.installer is not None and self.sums is not None

    @property
    def date(self) -> str:
        return self.published_at[:10]


def _read_limited(resp, limit: int) -> bytes:
    data = resp.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("Resposta maior que o esperado; abortado.")
    return data


def _require_download_url(url: str) -> None:
    if not url.startswith(_DOWNLOAD_PREFIX):
        raise UpdateError("Endereço de download fora da Release do projeto; recusado.")


def _check_final_host(resp, fallback: str) -> None:
    final = getattr(resp, "geturl", lambda: fallback)()
    parsed = urlparse(final)
    if parsed.scheme != "https" or parsed.hostname not in _DOWNLOAD_HOSTS:
        raise UpdateError(f"O download foi redirecionado para um destino não confiável ({parsed.hostname}).")


def _request(url: str, accept: str) -> Request:
    return Request(url, headers={"User-Agent": f"EdgeMD/{__version__}", "Accept": accept})


def parse_releases(payload: list[dict], *, include_prereleases: bool = False) -> list[Release]:
    """Converte a resposta da API em Releases, da mais nova para a mais antiga.

    Rascunhos são ignorados (a API só os mostra a quem tem permissão, mas a
    checagem não custa nada), assim como tags que não são SemVer.
    """
    releases: list[Release] = []
    for item in payload:
        if item.get("draft"):
            continue
        if item.get("prerelease") and not include_prereleases:
            continue
        version = clean_version(item.get("tag_name", ""))
        if parse_version(version) is None:
            continue
        assets = {
            a["name"]: Asset(a["name"], a.get("browser_download_url", ""), int(a.get("size") or 0))
            for a in item.get("assets", [])
            if a.get("name")
        }
        releases.append(
            Release(
                tag=item["tag_name"],
                version=version,
                name=item.get("name") or item["tag_name"],
                body=item.get("body") or "",
                html_url=item.get("html_url") or RELEASES_PAGE,
                published_at=item.get("published_at") or "",
                prerelease=bool(item.get("prerelease")),
                assets=assets,
            )
        )
    releases.sort(key=lambda r: parse_version(r.version), reverse=True)
    return releases


def fetch_releases(*, opener: Callable | None = None, include_prereleases: bool = False) -> list[Release]:
    """Lista as Releases publicadas. Levanta UpdateError se a rede falhar."""
    try:
        with (opener or urlopen)(_request(RELEASES_API, "application/vnd.github+json"), timeout=API_TIMEOUT) as resp:
            payload = json.loads(_read_limited(resp, MAX_API_BYTES).decode("utf-8"))
    except (URLError, OSError, ValueError) as exc:
        raise UpdateError(f"Não foi possível consultar o GitHub: {exc}") from exc
    if not isinstance(payload, list):
        raise UpdateError("Resposta inesperada do GitHub.")
    return parse_releases(payload, include_prereleases=include_prereleases)


def newest_update(releases: list[Release], current: str = __version__) -> Release | None:
    """A Release mais nova que a versão em uso, ou None."""
    if releases and is_newer(releases[0].version, current):  # já vem da mais nova
        return releases[0]
    return None


# ---------------------------------------------------------------------------
# Checksums e download
# ---------------------------------------------------------------------------
def parse_sums(text: str) -> dict[str, str]:
    """Lê o formato do ``sha256sum``: ``<hash>  <arquivo>`` (ou ``*<arquivo>``)."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m:
            sums[m.group(2)] = m.group(1).lower()
    return sums


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_hash(release: Release, *, opener: Callable | None = None) -> str:
    """O SHA-256 que o instalador desta Release deve ter, segundo o SHA256SUMS."""
    installer, sums = release.installer, release.sums
    if installer is None or sums is None:
        raise UpdateError("Esta Release não tem instalador com checksum para o Windows.")
    _require_download_url(sums.url)
    try:
        with (opener or urlopen)(_request(sums.url, "application/octet-stream"), timeout=API_TIMEOUT) as resp:
            _check_final_host(resp, sums.url)
            text = _read_limited(resp, 256 * 1024).decode("utf-8", errors="replace")
    except (URLError, OSError) as exc:
        raise UpdateError(f"Não foi possível baixar o {SUMS_NAME}: {exc}") from exc
    wanted = parse_sums(text).get(installer.name)
    if not wanted:
        raise UpdateError(f"O {SUMS_NAME} não lista {installer.name}.")
    return wanted


def cache_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "EdgeMD" / "updates"


def cached_installer(release: Release, root: Path | None = None) -> Path | None:
    """O instalador desta versão já guardado, se existir (sem conferir o hash)."""
    installer = release.installer
    if installer is None:
        return None
    path = (root or cache_root()) / release.version / installer.name
    return path if path.is_file() else None


def download_installer(
    release: Release,
    *,
    root: Path | None = None,
    opener: Callable | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Path:
    """Baixa (ou reaproveita do cache) o instalador e o confere contra o SHA-256.

    Só devolve um caminho depois de o hash bater. Em qualquer divergência o
    arquivo é apagado: um instalador que falhou na conferência nunca fica no
    disco com cara de utilizável.
    """
    installer = release.installer
    if installer is None:
        raise UpdateError("Esta Release não tem instalador para o Windows.")
    if not INSTALLER_RE.match(installer.name):  # defesa em profundidade; ver parse
        raise UpdateError("Nome de instalador inesperado.")
    _require_download_url(installer.url)

    wanted = expected_hash(release, opener=opener)
    folder = (root or cache_root()) / release.version
    target = folder / installer.name

    if target.is_file():
        if sha256_file(target) == wanted:
            log.info("Instalador %s reaproveitado do cache", installer.name)
            return target
        log.warning("Cache de %s não confere; baixando de novo", installer.name)
        target.unlink(missing_ok=True)

    folder.mkdir(parents=True, exist_ok=True)
    part = folder / (installer.name + ".part")
    digest = hashlib.sha256()
    received = 0
    try:
        with (opener or urlopen)(_request(installer.url, "application/octet-stream"), timeout=DOWNLOAD_TIMEOUT) as resp:
            _check_final_host(resp, installer.url)
            total = int(getattr(resp, "headers", {}).get("Content-Length", 0) or installer.size or 0)
            if total > MAX_INSTALLER_BYTES:
                raise UpdateError("O instalador é maior que o limite aceito.")
            with part.open("wb") as out:
                while True:
                    if cancelled and cancelled():
                        raise Cancelled("Download cancelado.")
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > MAX_INSTALLER_BYTES:
                        raise UpdateError("O instalador é maior que o limite aceito.")
                    digest.update(chunk)
                    out.write(chunk)
                    if progress:
                        progress(received, total)
        if digest.hexdigest() != wanted:
            raise ChecksumError(
                "O arquivo baixado não confere com o SHA-256 publicado. "
                "Ele foi descartado; nada foi instalado."
            )
        os.replace(part, target)
    except (URLError, OSError) as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(f"Falha no download: {exc}") from exc
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    return target


def prune_cache(keep_versions: list[str], *, root: Path | None = None, keep: int = CACHE_KEEP) -> list[str]:
    """Apaga instaladores antigos, mantendo os ``keep`` mais recentes em uso.

    ``keep_versions`` vem em ordem de prioridade (a versão em uso primeiro, depois
    a recém-instalada...). O que sobra é o backup local para voltar sem rede.
    """
    base = root or cache_root()
    if not base.is_dir():
        return []
    protegidas = set(keep_versions[:keep])
    removidas = []
    for child in base.iterdir():
        if child.is_dir() and child.name not in protegidas:
            shutil.rmtree(child, ignore_errors=True)
            removidas.append(child.name)
    return removidas


# ---------------------------------------------------------------------------
# Instalação
# ---------------------------------------------------------------------------
def install_dir() -> Path | None:
    return Path(sys.executable).parent if is_frozen() else None


def can_self_install() -> bool:
    """True só no Windows, num app instalado pelo instalador .exe (Inno Setup).

    O desinstalador do Inno (``unins000.exe``) ao lado do executável é a marca de
    que o app veio dele. Código-fonte, AppImage, .deb, .dmg e MSIX não atualizam
    sozinhos: nesses casos o app só avisa e abre a página da Release.
    """
    if sys.platform != "win32":
        return False
    folder = install_dir()
    return folder is not None and (folder / "unins000.exe").is_file()


def installer_arguments(log_path: Path | None = None) -> list[str]:
    args = ["/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELAUNCH"]
    if log_path:
        args.append(f"/LOG={log_path}")
    return args


def launch_installer(path: Path) -> None:
    """Dispara o instalador desacoplado do app, que em seguida se encerra."""
    if sys.platform != "win32":
        raise UpdateError("A instalação automática só existe no Windows.")
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    log_path = path.parent / "instalacao.log"
    subprocess.Popen(  # noqa: S603 - caminho verificado por SHA-256
        [str(path), *installer_arguments(log_path)],
        creationflags=flags,
        close_fds=True,
    )


# ---------------------------------------------------------------------------
# Reportar problema
# ---------------------------------------------------------------------------
def describe_system() -> str:
    """Nome do sistema no vocabulário do formulário de bug."""
    if sys.platform == "win32":
        try:
            build = int(platform.version().split(".")[2])
        except (IndexError, ValueError):
            build = 0
        return "Windows 11" if build >= 22000 else "Windows 10"
    if sys.platform == "darwin":
        return "macOS"
    if sys.platform.startswith("linux"):
        return "Linux"
    return "Outro"


def describe_install() -> str:
    if not is_frozen():
        return "Código-fonte (pip/python)"
    if can_self_install():
        return "Instalador .exe"
    return "Outro"


def report_problem_url() -> str:
    """Abre o formulário de bug já com versão e sistema preenchidos.

    Só vai no endereço o que o usuário vê na tela e pode apagar antes de enviar:
    versão, sistema e forma de instalação. Nada de caminho, nome ou documento.
    """
    campos = {"template": "bug.yml", "versao": __version__, "sistema": describe_system()}
    install = describe_install()
    if install != "Outro":
        campos["instalacao"] = install
    return f"https://github.com/{REPO}/issues/new?" + urlencode(campos)


# ---------------------------------------------------------------------------
# Frequência da checagem
# ---------------------------------------------------------------------------
def should_check(last_check: float, now: float | None = None, interval: int = CHECK_INTERVAL_SECONDS) -> bool:
    return ((now if now is not None else time.time()) - last_check) >= interval
