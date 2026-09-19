"""Testes da associação de arquivos.

Estes testes escrevem no registro de verdade, então usam um ProgID, uma
extensão e uma pasta de Capabilities **exclusivos de teste**, todos removidos
no fim. Nenhum deles toca em ``.md`` nem nas associações reais do usuário — um
teste que mexe na associação de arquivos de quem o executa seria inaceitável.
"""

from __future__ import annotations

import sys

import pytest

from edgemd.association import common
from edgemd.association import windows as fa

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="a associação de arquivos é específica do Windows"
)


TEST_PROG_ID = "EdgeMD.PytestOnly"
TEST_EXTENSION = ".mdpytestonly"
TEST_CAPABILITIES = r"Software\EdgeMD.Pytest\Capabilities"
TEST_APP_NAME = "EdgeMD Pytest"
TEST_EXE_NAME = "edgemd-pytest.exe"
TEST_LAUNCHER = [rf"C:\edgemd-pytest\{TEST_EXE_NAME}"]


@pytest.fixture
def isolated(monkeypatch):
    """Redireciona o módulo para chaves de teste e limpa depois.

    A limpeza apaga a árvore inteira de ``.mdpytestonly``. Isso é seguro
    justamente porque a extensão é inventada: nenhum arquivo real pode
    depender dela. Sem remover a chave inteira, o valor padrão e os
    OpenWithProgids vazariam de um teste para o outro.
    """
    monkeypatch.setattr(fa, "PROG_ID", TEST_PROG_ID)
    monkeypatch.setattr(fa, "EXTENSIONS", (TEST_EXTENSION,))
    monkeypatch.setattr(fa, "CAPABILITIES_PATH", TEST_CAPABILITIES)
    monkeypatch.setattr(fa, "APP_FRIENDLY_NAME", TEST_APP_NAME)

    import winreg

    root = winreg.HKEY_CURRENT_USER
    fa.delete_tree(root, rf"Software\Classes\{TEST_EXTENSION}")

    yield

    fa.delete_tree(root, rf"Software\Classes\{TEST_EXTENSION}")
    fa.delete_tree(root, rf"Software\Classes\{TEST_PROG_ID}")
    fa.delete_tree(root, rf"Software\Classes\Applications\{TEST_EXE_NAME}")
    fa.delete_tree(root, TEST_CAPABILITIES)
    fa.delete_tree(root, r"Software\EdgeMD.Pytest")
    try:
        with winreg.OpenKey(
            root, r"Software\RegisteredApplications", 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, TEST_APP_NAME)
    except (FileNotFoundError, OSError):
        pass


# --------------------------------------------------------------------------
# Comando
# --------------------------------------------------------------------------

class TestBuildCommand:
    """O comando é montado pelo comum; o Windows fornece o marcador citado.

    As aspas em volta do ``%1`` são decisão do backend, não da montagem: no
    Windows sem elas um caminho com espaço chegaria partido em dois argumentos,
    enquanto no Linux citar o ``%F`` juntaria todos os arquivos num só.
    """

    def test_marcador_do_windows_vem_citado(self):
        assert fa.FILE_PLACEHOLDER == '"%1"'

    def test_cita_caminhos_com_espaco(self):
        comando = fa.build_command(
            [r"C:\Program Files\App\app.exe"], fa.FILE_PLACEHOLDER
        )
        assert comando == '"C:\\Program Files\\App\\app.exe" "%1"'

    def test_dois_argumentos(self):
        comando = fa.build_command(
            [r"C:\Python\pythonw.exe", r"C:\app\run.pyw"], fa.FILE_PLACEHOLDER
        )
        assert comando == '"C:\\Python\\pythonw.exe" "C:\\app\\run.pyw" "%1"'

    def test_nao_cita_duas_vezes(self):
        comando = fa.build_command(['"C:\\ja\\citado.exe"'], fa.FILE_PLACEHOLDER)
        assert comando.count('"C:\\ja\\citado.exe"') == 1

    def test_marcador_sobrevive_a_montagem(self):
        assert fa.build_command(["a.exe"], fa.FILE_PLACEHOLDER).endswith('"%1"')

    def test_registro_usa_o_marcador_do_backend(self):
        """O comando gravado no registro precisa ter as aspas."""
        assert fa.status([r"C:\app\edgemd.exe"]).command.endswith('"%1"')


# --------------------------------------------------------------------------
# Leitura de estado
# --------------------------------------------------------------------------

class TestStatus:
    def test_le_sem_escrever(self, isolated):
        antes = fa.status(TEST_LAUNCHER)
        assert antes.is_default is False
        assert antes.in_open_with is False

        # Uma leitura não pode criar nada.
        depois = fa.status(TEST_LAUNCHER)
        assert depois == antes

    def test_needs_update_quando_comando_difere(self, isolated):
        fa.register(TEST_LAUNCHER)
        # Simula o app ter sido movido de pasta: o registro aponta para o
        # comando antigo.
        outro = fa.status([r"D:\outro\lugar.exe"])
        assert outro.needs_update is True

    def test_needs_update_false_quando_igual(self, isolated):
        fa.register(TEST_LAUNCHER)
        assert fa.status(TEST_LAUNCHER).needs_update is False


# --------------------------------------------------------------------------
# Registro
# --------------------------------------------------------------------------

class TestRegister:
    def test_registra_como_padrao(self, isolated):
        resultado = fa.register(TEST_LAUNCHER, make_default=True)
        assert resultado.is_default is True
        assert resultado.in_open_with is True
        assert resultado.registered_command == fa.build_command(TEST_LAUNCHER, fa.FILE_PLACEHOLDER)

    def test_apenas_abrir_com(self, isolated):
        resultado = fa.register(TEST_LAUNCHER, make_default=False)
        # Presente em "Abrir com", mas sem assumir o padrão.
        assert resultado.in_open_with is True
        assert resultado.is_default is False

    def test_nao_quebra_o_padrao_existente(self, isolated):
        """make_default=False não pode roubar uma escolha já feita."""
        import winreg

        root = winreg.HKEY_CURRENT_USER
        outro = "OutroApp.Document"
        fa._set_default(root, rf"Software\Classes\{TEST_EXTENSION}", outro)
        try:
            fa.register(TEST_LAUNCHER, make_default=False)
            atual = fa._read_default(root, rf"Software\Classes\{TEST_EXTENSION}")
            assert atual == outro
        finally:
            try:
                with winreg.OpenKey(
                    root, rf"Software\Classes\{TEST_EXTENSION}", 0, winreg.KEY_SET_VALUE
                ) as key:
                    winreg.DeleteValue(key, "")
            except (FileNotFoundError, OSError):
                pass

    def test_nao_registra_applications_do_python(self, isolated):
        """Rodando do código-fonte, o launcher é pythonw.exe.

        Registrar Applications\\pythonw.exe mudaria como todos os .pyw do
        usuário abrem — o teste garante que isso não acontece.
        """
        import winreg

        fa.register([r"C:\Python314\pythonw.exe", r"C:\app\run.pyw"])
        root = winreg.HKEY_CURRENT_USER
        assert not fa._key_exists(
            root, r"Software\Classes\Applications\pythonw.exe"
        )

    def test_registra_capabilities(self, isolated):
        import winreg

        fa.register(TEST_LAUNCHER)
        root = winreg.HKEY_CURRENT_USER
        assert fa._key_exists(root, TEST_CAPABILITIES)

        # TEST_APP_NAME é NOME de valor sob RegisteredApplications, não uma
        # subchave — por isso a leitura é pelo nome, não pelo valor padrão.
        with winreg.OpenKey(root, r"Software\RegisteredApplications") as key:
            registrado, _tipo = winreg.QueryValueEx(key, TEST_APP_NAME)
        assert registrado == TEST_CAPABILITIES

        with winreg.OpenKey(root, rf"{TEST_CAPABILITIES}\FileAssociations") as key:
            valor, _tipo = winreg.QueryValueEx(key, TEST_EXTENSION)
        assert valor == TEST_PROG_ID

    def test_grava_o_comando(self, isolated):
        import winreg

        fa.register(TEST_LAUNCHER)
        comando = fa._read_default(
            winreg.HKEY_CURRENT_USER,
            rf"Software\Classes\{TEST_PROG_ID}\shell\open\command",
        )
        assert comando == fa.build_command(TEST_LAUNCHER, fa.FILE_PLACEHOLDER)
        assert "%1" in comando

    def test_grava_o_icone_quando_existe(self, isolated):
        import winreg

        from edgemd.paths import icon_path

        ico = icon_path("edgemd.ico")
        if not ico.is_file():
            pytest.skip("ícone não gerado; rode tools/make_icons.py")

        fa.register(TEST_LAUNCHER)
        valor = fa._read_default(
            winreg.HKEY_CURRENT_USER,
            rf"Software\Classes\{TEST_PROG_ID}\DefaultIcon",
        )
        assert valor is not None
        assert f"{ico},0" == valor

    def test_idempotente(self, isolated):
        primeiro = fa.register(TEST_LAUNCHER)
        segundo = fa.register(TEST_LAUNCHER)
        assert primeiro.command == segundo.command
        assert primeiro.registered_command == segundo.registered_command


# --------------------------------------------------------------------------
# Remoção
# --------------------------------------------------------------------------

class TestUnregister:
    def test_remove_o_que_criou(self, isolated):
        import winreg

        fa.register(TEST_LAUNCHER, make_default=True)
        # unregister() mexe nas extensões do módulo, já redirecionadas pelo
        # fixture, então age só nas chaves de teste.
        fa.unregister()

        root = winreg.HKEY_CURRENT_USER
        assert not fa._key_exists(root, rf"Software\Classes\{TEST_PROG_ID}")
        status = fa.status(TEST_LAUNCHER)
        assert status.is_default is False
        assert status.in_open_with is False

    def test_preserva_padrao_de_outro_app(self, isolated):
        """Se o usuário trocou o padrão depois, a escolha dele prevalece."""
        import winreg

        root = winreg.HKEY_CURRENT_USER
        outro = "OutroApp.Document"
        fa.register(TEST_LAUNCHER, make_default=True)

        fa._set_default(root, rf"Software\Classes\{TEST_EXTENSION}", outro)
        try:
            fa.unregister()
            atual = fa._read_default(root, rf"Software\Classes\{TEST_EXTENSION}")
            assert atual == outro
        finally:
            try:
                with winreg.OpenKey(
                    root, rf"Software\Classes\{TEST_EXTENSION}", 0, winreg.KEY_SET_VALUE
                ) as key:
                    winreg.DeleteValue(key, "")
            except (FileNotFoundError, OSError):
                pass

    def test_remover_duas_vezes_nao_explode(self, isolated):
        fa.register(TEST_LAUNCHER)
        fa.unregister()
        fa.unregister()  # não deve levantar


# --------------------------------------------------------------------------
# Constantes de produção
# --------------------------------------------------------------------------

class TestConstantes:
    def test_progid_nao_colide_com_teste(self):
        assert fa.PROG_ID != TEST_PROG_ID
        assert TEST_EXTENSION not in fa.EXTENSIONS

    def test_extensoes_cobrem_md(self):
        assert ".md" in fa.EXTENSIONS
        assert ".markdown" in fa.EXTENSIONS

    def test_tudo_em_hkcu(self):
        # HKEY_CLASSES_ROOT exigiria administrador; o app não pede isso.
        assert not fa.CAPABILITIES_PATH.startswith("\\")
        assert "HKEY_CLASSES_ROOT" not in fa.CAPABILITIES_PATH
