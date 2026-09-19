#!/usr/bin/env bash
# Gera um AppImage do EdgeMD.
#
# Uso:
#   pyinstaller edgemd.spec --noconfirm --clean
#   packaging/linux/build_appimage.sh [versão]
#
# Por que AppImage além do .deb: o .deb só serve em Debian e derivados, e só na
# arquitetura para que foi compilado. O AppImage roda em qualquer distribuição
# com glibc compatível, sem instalar nada — é o formato que dá para baixar e
# usar direto.
#
# A associação de arquivos fica de fora aqui, de propósito: um AppImage é um
# arquivo só, que o usuário pode mover ou apagar, e registrar um caminho desses
# no sistema deixaria uma associação quebrada. Quem quer associação instala o
# .deb ou usa Ferramentas → Associar dentro do app depois de guardá-lo num
# lugar definitivo.

set -euo pipefail

VERSAO="${1:-0.1.0}"

# A versao vai para dentro do pacote, e o dpkg-deb recusa valor que nao comeca
# com digito. Sem esta checagem, passar "main" por engano dava um erro do
# dpkg-deb sobre o campo Version, sem dizer de onde vinha o valor.
if ! printf '%s' "$VERSAO" | grep -qE '^[0-9]'; then
    echo "ERRO: versão inválida: '$VERSAO'" >&2
    echo "       Precisa começar com dígito (ex.: 0.1.0)." >&2
    exit 1
fi

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ORIGEM="$RAIZ/dist/edgemd"
DESTINO="$RAIZ/dist/linux"
APPDIR="$DESTINO/EdgeMD.AppDir"

if [ ! -x "$ORIGEM/edgemd" ]; then
    echo "ERRO: $ORIGEM/edgemd não existe." >&2
    echo "Gere o bundle antes:  pyinstaller edgemd.spec --noconfirm --clean" >&2
    exit 1
fi

echo "==> Preparando o AppDir"
rm -rf "$APPDIR"
mkdir -p "$DESTINO"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

cp -r "$ORIGEM/." "$APPDIR/usr/bin/"

# ---------------------------------------------------------------------------
# Ícone, atalho e AppRun
# ---------------------------------------------------------------------------
ICONE="$RAIZ/src/edgemd/resources/icons/edgemd.png"
if [ -f "$ICONE" ]; then
    cp "$ICONE" "$APPDIR/usr/share/icons/hicolor/256x256/apps/edgemd.png"
    cp "$ICONE" "$APPDIR/edgemd.png"
fi

# O .desktop na raiz do AppDir é o que o integrador opcional lê.
cat > "$APPDIR/edgemd.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=EdgeMD
GenericName=Leitor de Markdown
Comment=Leia e edite arquivos Markdown
Exec=edgemd %F
Icon=edgemd
Terminal=false
Categories=Utility;TextEditor;Office;
MimeType=text/markdown;text/x-markdown;
StartupNotify=true
StartupWMClass=EdgeMD
Keywords=markdown;md;texto;editor;leitor;
DESKTOP
cp "$APPDIR/edgemd.desktop" "$APPDIR/usr/share/applications/edgemd.desktop"

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
# Ponto de entrada do AppImage: o Qt procura os próprios plugins em caminhos
# relativos ao executável, e o AppImage é montado num diretório temporário.
# Sem ajustar isto, o WebEngine não encontra os recursos e o preview sobe vazio.
AQUI="$(dirname "$(readlink -f "$0")")"
export LD_LIBRARY_PATH="$AQUI/usr/bin:${LD_LIBRARY_PATH:-}"
export QT_PLUGIN_PATH="$AQUI/usr/bin/PyQt6/Qt6/plugins:${QT_PLUGIN_PATH:-}"
export QTWEBENGINE_RESOURCES_PATH="$AQUI/usr/bin/PyQt6/Qt6/resources"
export QTWEBENGINE_LOCALES_PATH="$AQUI/usr/bin/PyQt6/Qt6/translations/qtwebengine_locales"
exec "$AQUI/usr/bin/edgemd" "$@"
APPRUN
chmod 0755 "$APPDIR/AppRun"

# ---------------------------------------------------------------------------
# Empacotamento
# ---------------------------------------------------------------------------
SAIDA="$DESTINO/EdgeMD-${VERSAO}-x86_64.AppImage"

buscar_appimagetool() {
    if command -v appimagetool >/dev/null 2>&1; then
        command -v appimagetool
        return
    fi
    if [ -x "$DESTINO/appimagetool" ]; then
        echo "$DESTINO/appimagetool"
        return
    fi
    echo "==> Baixando o appimagetool"
    local url="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    if command -v curl >/dev/null 2>&1; then
        curl -sSL -o "$DESTINO/appimagetool" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$DESTINO/appimagetool" "$url"
    else
        return 1
    fi
    chmod +x "$DESTINO/appimagetool"
    echo "$DESTINO/appimagetool"
}

if FERRAMENTA="$(buscar_appimagetool)"; then
    echo "==> Montando o AppImage"
    # O appimagetool é ele mesmo um AppImage: precisa de FUSE, que não existe
    # em todo contêiner. EXTRAIR_AND_RUN evita essa dependência.
    ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 \
        "$FERRAMENTA" "$APPDIR" "$SAIDA" >/dev/null

    echo
    echo "Pronto: $SAIDA"
    echo "Dê permissão de execução e rode:  chmod +x '$SAIDA' && '$SAIDA'"
else
    echo "AVISO: não consegui obter o appimagetool." >&2
    echo "A árvore do AppDir está pronta em $APPDIR" >&2
    exit 1
fi
