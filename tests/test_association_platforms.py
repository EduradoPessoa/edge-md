"""Testes dos backends de Linux e macOS e da fachada de plataforma.

Os testes de Linux e macOS rodam **em qualquer sistema**: os dois backends
escrevem em arquivos cujos diretórios-base vêm de variáveis de ambiente
(``XDG_DATA_HOME``, ``XDG_CONFIG_HOME``) ou de um caminho derivado do
executável, e ambos são redirecionáveis para uma pasta temporária. Sem isso, a
lógica só seria verificável rodando a suíte em três máquinas diferentes.

O que não dá para testar assim é a chamada aos utilitários do sistema
(``xdg-mime``, ``duti``, ``update-desktop-database``): eles são procurados no
PATH e, quando ausentes, o backend segue pelo caminho de reserva — que é
justamente o que os testes exercitam.
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

import pytest

from edgemd.association import linux, macos
from edgemd.association.common import (
    APP_BUNDLE_ID,
    MIME_TYPES,
    AssociationStatus,
    build_command,
)


# ==========================================================================
# Linux
# ==========================================================================

@pytest.fixture
def xdg(tmp_path, monkeypatch):
    """Isola os diretórios XDG numa pasta temporária.

    O backend lê as variáveis a cada chamada, e não uma vez no import — sem
    isso, apontar aqui não teria efeito.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    # Sinaliza o suporte em vez de mexer em sys.platform: a checagem do backend
    # é dinâmica justamente para poder ser trocada assim.
    monkeypatch.setattr(linux, "is_supported", lambda: True)
    # Sem estes utilitários, o backend escreve os arquivos por conta própria,
    # que é o caminho que interessa verificar.
    monkeypatch.setattr(linux.shutil, "which", lambda _nome: None)
    return tmp_path


class TestCaminhosLinux:
    def test_desktop_em_share(self, xdg):
        assert linux.desktop_path() == xdg / "share" / "applications" / "edgemd.desktop"

    def test_mimeapps_em_config(self, xdg):
        assert linux.mimeapps_path() == xdg / "config" / "mimeapps.list"

    def test_icones_por_tamanho(self, xdg):
        assert linux.icon_dir(256) == (
            xdg / "share" / "icons" / "hicolor" / "256x256" / "apps"
        )

    def test_marcador_sem_aspas(self):
        """No .desktop, citar o %F juntaria todos os arquivos num argumento."""
        assert linux.PLACEHOLDER == "%F"


class TestRegistroLinux:
    def test_cria_o_desktop(self, xdg):
        linux.register(["/usr/bin/edgemd"], make_default=True)

        caminho = linux.desktop_path()
        assert caminho.is_file()

        conteudo = caminho.read_text(encoding="utf-8")
        assert "[Desktop Entry]" in conteudo
        assert "Name=EdgeMD" in conteudo
        assert 'Exec="/usr/bin/edgemd" %F' in conteudo
        assert "Icon=edgemd" in conteudo

    def test_declara_os_tipos_mime(self, xdg):
        """Sem MimeType= o programa não aparece em Abrir com."""
        linux.register(["/usr/bin/edgemd"], make_default=True)
        conteudo = linux.desktop_path().read_text(encoding="utf-8")
        for mime in MIME_TYPES:
            assert mime in conteudo

    def test_nao_abre_terminal(self, xdg):
        linux.register(["/usr/bin/edgemd"], make_default=True)
        assert "Terminal=false" in linux.desktop_path().read_text(encoding="utf-8")

    def test_executavel(self, xdg):
        """O bit de execução só existe em sistema POSIX.

        No Windows o ``chmod`` mexe apenas no atributo de somente-leitura, então
        verificar isso lá testaria outra coisa.
        """
        if sys.platform == "win32":
            pytest.skip("bit de execução não existe no Windows")

        linux.register(["/usr/bin/edgemd"], make_default=True)
        modo = linux.desktop_path().stat().st_mode
        assert modo & 0o111, "o .desktop precisa ser executável"

    def test_comando_com_espaco_no_caminho(self, xdg):
        linux.register(["/home/jose/Meus Programas/edgemd"], make_default=True)
        conteudo = linux.desktop_path().read_text(encoding="utf-8")
        assert 'Exec="/home/jose/Meus Programas/edgemd" %F' in conteudo

    def test_define_padrao_sem_xdg_mime(self, xdg):
        """Sem o xdg-mime, o mimeapps.list é escrito à mão."""
        linux.register(["/usr/bin/edgemd"], make_default=True)

        conteudo = linux.mimeapps_path().read_text(encoding="utf-8")
        assert "[Default Applications]" in conteudo
        assert f"{MIME_TYPES[0]}=edgemd.desktop" in conteudo

    def test_nao_toca_no_padrao_quando_nao_pedido(self, xdg):
        linux.register(["/usr/bin/edgemd"], make_default=False)
        assert linux.desktop_path().is_file()
        assert not linux.mimeapps_path().exists()

    def test_idempotente(self, xdg):
        linux.register(["/usr/bin/edgemd"], make_default=True)
        primeiro = linux.desktop_path().read_text(encoding="utf-8")
        linux.register(["/usr/bin/edgemd"], make_default=True)
        assert linux.desktop_path().read_text(encoding="utf-8") == primeiro

    def test_reaproveita_secao_existente(self, xdg):
        """Não pode criar uma segunda [Default Applications] no arquivo."""
        caminho = linux.mimeapps_path()
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(
            "[Added Associations]\n"
            "text/plain=outro.desktop;\n"
            "\n"
            "[Default Applications]\n"
            "text/plain=outro.desktop\n",
            encoding="utf-8",
        )

        linux.register(["/usr/bin/edgemd"], make_default=True)

        conteudo = caminho.read_text(encoding="utf-8")
        assert conteudo.count("[Default Applications]") == 1
        assert "text/plain=outro.desktop" in conteudo
        assert f"{MIME_TYPES[0]}=edgemd.desktop" in conteudo

    def test_cria_secao_quando_nao_existe(self, xdg):
        caminho = linux.mimeapps_path()
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text("[Added Associations]\ntext/plain=outro.desktop;\n", encoding="utf-8")

        linux.register(["/usr/bin/edgemd"], make_default=True)

        conteudo = caminho.read_text(encoding="utf-8")
        assert "[Default Applications]" in conteudo
        assert "[Added Associations]" in conteudo


class TestStatusLinux:
    def test_sem_registro(self, xdg):
        estado = linux.status(["/usr/bin/edgemd"])
        assert estado.supported is True
        assert estado.in_open_with is False
        assert estado.is_default is False

    def test_depois_de_registrar(self, xdg):
        linux.register(["/usr/bin/edgemd"], make_default=True)
        estado = linux.status(["/usr/bin/edgemd"])
        assert estado.in_open_with is True
        assert estado.is_default is True
        assert estado.needs_update is False

    def test_detecta_comando_desatualizado(self, xdg):
        """App movido de pasta: o registro aponta para o caminho antigo."""
        linux.register(["/opt/antigo/edgemd"], make_default=True)
        estado = linux.status(["/opt/novo/edgemd"])
        assert estado.needs_update is True

    def test_sem_launcher_nao_compara(self, xdg):
        linux.register(["/usr/bin/edgemd"], make_default=True)
        estado = linux.status(None)
        assert estado.command is None
        assert estado.needs_update is False


class TestRemocaoLinux:
    def test_remove_o_desktop(self, xdg):
        linux.register(["/usr/bin/edgemd"], make_default=True)
        linux.unregister()
        assert not linux.desktop_path().exists()

    def test_devolve_o_padrao(self, xdg):
        linux.register(["/usr/bin/edgemd"], make_default=True)
        assert linux.status(["/usr/bin/edgemd"]).is_default is True

        linux.unregister()
        assert linux.status(["/usr/bin/edgemd"]).is_default is False

    def test_preserva_padrao_de_outro_app(self, xdg):
        caminho = linux.mimeapps_path()
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(
            "[Default Applications]\ntext/plain=outro.desktop\n", encoding="utf-8"
        )

        linux.register(["/usr/bin/edgemd"], make_default=True)
        linux.unregister()

        assert "text/plain=outro.desktop" in caminho.read_text(encoding="utf-8")

    def test_remover_duas_vezes_nao_explode(self, xdg):
        linux.register(["/usr/bin/edgemd"], make_default=True)
        linux.unregister()
        linux.unregister()


class TestIconesLinux:
    def test_instala_tamanhos(self, xdg, tmp_path):
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow não instalado")

        origem = tmp_path / "icone.png"
        Image.new("RGBA", (512, 512), (0, 0, 0, 255)).save(origem)

        linux.register(["/usr/bin/edgemd"], icon_file=origem, make_default=True)

        for size in (16, 48, 256):
            destino = linux.icon_dir(size) / "edgemd.png"
            assert destino.is_file(), f"faltou o ícone de {size}px"
            with Image.open(destino) as imagem:
                assert imagem.size == (size, size)

    def test_sem_icone_nao_impede_o_registro(self, xdg, tmp_path):
        linux.register(
            ["/usr/bin/edgemd"], icon_file=tmp_path / "nao-existe.png",
            make_default=True,
        )
        assert linux.desktop_path().is_file()


# ==========================================================================
# macOS
# ==========================================================================

@pytest.fixture
def bundle(tmp_path):
    """Cria a estrutura de um .app, com Info.plist, e o devolve."""
    app = tmp_path / "EdgeMD.app"
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)

    plist = {
        "CFBundleIdentifier": APP_BUNDLE_ID,
        "CFBundleName": "EdgeMD",
        "CFBundleExecutable": "edgemd",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Documento Markdown",
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Owner",
                "LSItemContentTypes": ["net.daringfireball.markdown"],
                "CFBundleTypeExtensions": ["md", "markdown"],
            }
        ],
    }
    with (contents / "Info.plist").open("wb") as arquivo:
        plistlib.dump(plist, arquivo)

    (contents / "MacOS" / "edgemd").write_text("", encoding="utf-8")
    return app


@pytest.fixture
def mac(monkeypatch, bundle):
    """Faz o backend do macOS enxergar o bundle falso.

    Aponta a costura ``_executable_path`` em vez de mexer em ``sys.executable``:
    o atributo é global, e trocá-lo afetaria toda a suíte durante o teste.
    """
    monkeypatch.setattr(macos, "is_supported", lambda: True)
    monkeypatch.setattr(
        macos, "_executable_path",
        lambda: bundle / "Contents" / "MacOS" / "edgemd",
    )
    return bundle


class TestBundleMacOS:
    def test_encontra_o_bundle(self, mac):
        assert macos.bundle_path() == mac

    def test_sem_bundle(self, monkeypatch, tmp_path):
        monkeypatch.setattr(macos, "is_supported", lambda: True)
        monkeypatch.setattr(macos, "_executable_path", lambda: tmp_path / "python")
        assert macos.bundle_path() is None

    def test_le_o_info_plist(self, mac):
        dados = macos.read_info_plist()
        assert dados["CFBundleIdentifier"] == APP_BUNDLE_ID

    def test_plist_ausente_devolve_vazio(self, monkeypatch, tmp_path):
        monkeypatch.setattr(macos, "is_supported", lambda: True)
        monkeypatch.setattr(macos, "_executable_path", lambda: tmp_path / "python")
        assert macos.read_info_plist() == {}


class TestDeclaracaoDeTipos:
    def test_reconhece_uti(self):
        plist = {
            "CFBundleDocumentTypes": [
                {"LSItemContentTypes": ["net.daringfireball.markdown"]}
            ]
        }
        assert macos.declares_document_types(plist) is True

    def test_reconhece_extensao(self):
        plist = {
            "CFBundleDocumentTypes": [{"CFBundleTypeExtensions": ["md", "txt"]}]
        }
        assert macos.declares_document_types(plist) is True

    def test_uti_errada(self):
        plist = {
            "CFBundleDocumentTypes": [{"LSItemContentTypes": ["public.jpeg"]}]
        }
        assert macos.declares_document_types(plist) is False

    def test_sem_a_chave(self):
        assert macos.declares_document_types({}) is False

    def test_entrada_malformada_nao_explode(self):
        plist = {"CFBundleDocumentTypes": ["texto solto", None, {}]}
        assert macos.declares_document_types(plist) is False


class TestStatusMacOS:
    def test_fora_de_bundle(self, monkeypatch, tmp_path):
        monkeypatch.setattr(macos, "is_supported", lambda: True)
        monkeypatch.setattr(macos, "_executable_path", lambda: tmp_path / "python")
        estado = macos.status([str(tmp_path / "python")])
        assert estado.in_open_with is False
        assert "bundle" in estado.detail.lower()

    def test_dentro_de_bundle_declarado(self, mac, monkeypatch):
        monkeypatch.setattr(macos, "duti_available", lambda: False)

        estado = macos.status(None)
        assert estado.in_open_with is True
        assert estado.registered_command == APP_BUNDLE_ID

    def test_bundle_sem_declaracao(self, mac, monkeypatch):
        monkeypatch.setattr(macos, "duti_available", lambda: False)

        caminho = mac / "Contents" / "Info.plist"
        with caminho.open("wb") as arquivo:
            plistlib.dump({"CFBundleIdentifier": APP_BUNDLE_ID}, arquivo)

        estado = macos.status(None)
        assert estado.in_open_with is False
        assert "CFBundleDocumentTypes" in estado.detail


class TestRegistroMacOS:
    def test_exige_bundle(self, monkeypatch, tmp_path):
        monkeypatch.setattr(macos, "is_supported", lambda: True)
        monkeypatch.setattr(macos, "_executable_path", lambda: tmp_path / "python")
        with pytest.raises(macos.AssociationError, match="empacotado"):
            macos.register([str(tmp_path / "python")])

    def test_exige_declaracao_no_plist(self, mac):
        caminho = mac / "Contents" / "Info.plist"
        with caminho.open("wb") as arquivo:
            plistlib.dump({"CFBundleIdentifier": APP_BUNDLE_ID}, arquivo)

        with pytest.raises(macos.AssociationError, match="CFBundleDocumentTypes"):
            macos.register([str(mac / "Contents" / "MacOS" / "edgemd")])

    def test_registrar_sem_duti_funciona(self, mac, monkeypatch):
        """Sem duti não dá para definir o padrão, mas o app já aparece."""
        monkeypatch.setattr(macos, "duti_available", lambda: False)

        estado = macos.register([str(mac / "Contents" / "MacOS" / "edgemd")])
        assert estado.in_open_with is True

    def test_unregister_sem_duti_nao_explode(self, mac, monkeypatch):
        monkeypatch.setattr(macos, "duti_available", lambda: False)
        macos.unregister()


# ==========================================================================
# Fachada
# ==========================================================================

class TestFachada:
    def test_escolhe_por_plataforma(self, monkeypatch):
        from edgemd import association

        monkeypatch.setattr(sys, "platform", "win32")
        assert association.backend() is association.windows

        monkeypatch.setattr(sys, "platform", "darwin")
        assert association.backend() is association.macos

        monkeypatch.setattr(sys, "platform", "linux")
        assert association.backend() is association.linux

    def test_plataforma_desconhecida_cai_no_linux(self, monkeypatch):
        """Os BSDs usam o mesmo .desktop."""
        from edgemd import association

        monkeypatch.setattr(sys, "platform", "freebsd")
        assert association.backend() is association.linux

    @pytest.mark.parametrize(
        "plataforma,esperado",
        [
            ("win32", "Windows"),
            ("darwin", "macOS"),
            ("linux", "Linux"),
        ],
    )
    def test_rotulo(self, monkeypatch, plataforma, esperado):
        from edgemd import association

        monkeypatch.setattr(sys, "platform", plataforma)
        assert association.platform_label() == esperado

    def test_status_nunca_levanta(self, monkeypatch):
        """A janela consulta o estado só para montar o diálogo; falhar ali
        impediria o usuário de até ver a mensagem de erro."""
        from edgemd import association

        def explode(*_a, **_k):
            raise association.AssociationError("falhou de propósito")

        monkeypatch.setattr(association.backend(), "status", explode)
        estado = association.status(None)
        assert estado.supported is False
        assert "propósito" in estado.detail

    def test_comando_por_plataforma(self):
        """O mesmo launcher gera comandos diferentes conforme o marcador.

        O caminho do programa é citado nos dois casos — pode ter espaço. O que
        muda entre plataformas é o marcador do arquivo, e só ele.
        """
        launcher = ["/usr/bin/edgemd"]
        assert build_command(launcher, linux.PLACEHOLDER) == '"/usr/bin/edgemd" %F'
        assert build_command(launcher, '"%1"') == '"/usr/bin/edgemd" "%1"'

    def test_marcador_do_linux_nao_e_citado(self):
        """Citar o %F juntaria todos os arquivos selecionados num argumento só."""
        assert not linux.PLACEHOLDER.startswith('"')

    def test_instrucoes_nao_vazias(self, monkeypatch):
        from edgemd import association

        for plataforma in ("win32", "darwin", "linux"):
            monkeypatch.setattr(sys, "platform", plataforma)
            assert association.instructions().strip()

    def test_extensoes_incluem_md(self):
        from edgemd.association.common import EXTENSIONS

        assert ".md" in EXTENSIONS
        assert ".markdown" in EXTENSIONS


class TestStatusComum:
    def test_needs_update_exige_os_dois_lados(self):
        sem_comando = AssociationStatus(
            supported=True, is_default=False, in_open_with=True, command=None,
            registered_command="algo",
        )
        assert sem_comando.needs_update is False

    def test_is_ours(self):
        padrao = AssociationStatus(
            supported=True, is_default=True, in_open_with=True
        )
        assert padrao.is_ours is True

        nada = AssociationStatus(
            supported=True, is_default=False, in_open_with=False
        )
        assert nada.is_ours is False
