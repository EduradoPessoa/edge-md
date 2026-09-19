#!/usr/bin/env bash
# Gera o pacote .deb do EdgeMD.
#
# Uso:
#   pyinstaller edgemd.spec --noconfirm --clean
#   packaging/linux/build_deb.sh [versão]
#
# O .deb é montado à mão, sem depender do debhelper: o programa já vem pronto do
# PyInstaller, então o pacote é basicamente copiar a pasta para /opt e instalar
# o .desktop, o ícone e os gatilhos que registram a associação.
#
# Sobre a associação: o arquivo .desktop com MimeType= é o que faz o app
# aparecer em "Abrir com", e o `update-desktop-database` no postinst é o que faz
# isso valer sem reiniciar a sessão.

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
ARQUITETURA="${DEB_ARCH:-amd64}"

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ORIGEM="$RAIZ/dist/edgemd"
DESTINO="$RAIZ/dist/linux"
PACOTE="$DESTINO/edgemd_${VERSAO}_${ARQUITETURA}"

if [ ! -x "$ORIGEM/edgemd" ]; then
    echo "ERRO: $ORIGEM/edgemd não existe." >&2
    echo "Gere o bundle antes:  pyinstaller edgemd.spec --noconfirm --clean" >&2
    exit 1
fi

echo "==> Limpando $PACOTE"
rm -rf "$PACOTE"
mkdir -p "$DESTINO"

# ---------------------------------------------------------------------------
# Estrutura do pacote
# ---------------------------------------------------------------------------
mkdir -p "$PACOTE/DEBIAN"
mkdir -p "$PACOTE/opt/edgemd"
mkdir -p "$PACOTE/usr/bin"
mkdir -p "$PACOTE/usr/share/applications"
mkdir -p "$PACOTE/usr/share/icons/hicolor"

echo "==> Copiando o bundle"
cp -r "$ORIGEM/." "$PACOTE/opt/edgemd/"

# Lançador em /usr/bin: /opt não costuma estar no PATH.
ln -sf /opt/edgemd/edgemd "$PACOTE/usr/bin/edgemd"

# ---------------------------------------------------------------------------
# Ícones em todos os tamanhos do tema hicolor
# ---------------------------------------------------------------------------
ICONE="$RAIZ/src/edgemd/resources/icons/edgemd.png"
if [ -f "$ICONE" ]; then
    echo "==> Instalando ícones"
    for tamanho in 16 24 32 48 64 128 256 512; do
        pasta="$PACOTE/usr/share/icons/hicolor/${tamanho}x${tamanho}/apps"
        mkdir -p "$pasta"
        if command -v convert >/dev/null 2>&1; then
            convert "$ICONE" -resize "${tamanho}x${tamanho}" "$pasta/edgemd.png"
        elif python3 -c "import PIL" 2>/dev/null; then
            python3 - "$ICONE" "$pasta/edgemd.png" "$tamanho" <<'PY'
import sys
from PIL import Image
origem, destino, tamanho = sys.argv[1], sys.argv[2], int(sys.argv[3])
with Image.open(origem) as imagem:
    imagem.convert("RGBA").resize((tamanho, tamanho), Image.LANCZOS).save(destino, "PNG")
PY
        else
            # Sem ferramenta de redimensionar, o PNG grande serve: o ambiente
            # gráfico reduz na hora de desenhar.
            cp "$ICONE" "$pasta/edgemd.png"
        fi
    done
fi

# ---------------------------------------------------------------------------
# Atalho
# ---------------------------------------------------------------------------
echo "==> Instalando o .desktop"
cat > "$PACOTE/usr/share/applications/edgemd.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Version=1.0
Name=EdgeMD
GenericName=Leitor de Markdown
Comment=Leia e edite arquivos Markdown
Exec=/opt/edgemd/edgemd %F
Icon=edgemd
Terminal=false
Categories=Utility;TextEditor;Office;
MimeType=text/markdown;text/x-markdown;
StartupNotify=true
StartupWMClass=EdgeMD
Keywords=markdown;md;texto;editor;leitor;
DESKTOP
chmod 0644 "$PACOTE/usr/share/applications/edgemd.desktop"

# ---------------------------------------------------------------------------
# Controle do pacote
# ---------------------------------------------------------------------------
TAMANHO=$(du -sk "$PACOTE/opt" | cut -f1)

cat > "$PACOTE/DEBIAN/control" <<CONTROL
Package: edgemd
Version: ${VERSAO}
Section: editors
Priority: optional
Architecture: ${ARQUITETURA}
Installed-Size: ${TAMANHO}
Depends: libgl1, libegl1, libxkbcommon0, libfontconfig1, libdbus-1-3
Recommends: fonts-noto-color-emoji
Maintainer: Eduardo Maurício Pessoa de Souza <eduardo@phoenyx.com.br>
Homepage: https://github.com/EduradoPessoa/edge-md
Description: Leitor e editor de Markdown
 Leitor e editor de Markdown com renderizacao por Chromium, diagramas
 Mermaid e formulas KaTeX que funcionam sem internet, tema claro e escuro
 em todo o aplicativo, e associacao de arquivos .md.
 .
 Abre lendo, e entra em edicao com um clique.
CONTROL

# Os gatilhos reconstroem os bancos de dados do freedesktop. Sem eles, o item
# no menu "Abrir com" só aparece depois de a sessão ser reiniciada.
cat > "$PACOTE/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi

exit 0
POSTINST
chmod 0755 "$PACOTE/DEBIAN/postinst"

cat > "$PACOTE/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi

exit 0
POSTRM
chmod 0755 "$PACOTE/DEBIAN/postrm"

# ---------------------------------------------------------------------------
# Empacotamento
# ---------------------------------------------------------------------------
echo "==> Montando o .deb"
if command -v dpkg-deb >/dev/null 2>&1; then
    dpkg-deb --build --root-owner-group "$PACOTE" "$DESTINO/edgemd_${VERSAO}_${ARQUITETURA}.deb"
    echo
    echo "Pronto: $DESTINO/edgemd_${VERSAO}_${ARQUITETURA}.deb"
    echo "Instale com:  sudo apt install $DESTINO/edgemd_${VERSAO}_${ARQUITETURA}.deb"
else
    # O debhelper não vem no runner do GitHub Actions por padrão; deixamos a
    # árvore pronta para quem tiver o dpkg-deb montar o pacote.
    echo "AVISO: dpkg-deb não encontrado. Estrutura pronta em $PACOTE" >&2
    exit 1
fi
