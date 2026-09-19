#!/usr/bin/env bash
# Gera o DMG do EdgeMD para macOS.
#
# Uso:
#   pyinstaller edgemd.spec --noconfirm --clean
#   packaging/macos/build_dmg.sh [versão]
#
# O bundle do PyInstaller já traz o Info.plist com CFBundleDocumentTypes, que é
# o que faz o macOS oferecer o EdgeMD em "Abrir com". O DMG é só a embalagem de
# distribuição: arrastar para Aplicativos é o gesto que o usuário espera.
#
# Sobre assinatura: sem uma conta de desenvolvedor Apple, o Gatekeeper avisa que
# o app é de origem desconhecida e o usuário precisa liberar em Ajustes →
# Privacidade e Segurança. O script assina ad-hoc quando é possível, o que
# resolve o caso de quem compila para si mesmo; distribuir para terceiros exige
# Developer ID e notarização, que dependem de credenciais.

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
APP="$RAIZ/dist/EdgeMD.app"
DESTINO="$RAIZ/dist/macos"
VOLUME="EdgeMD"

if [ ! -d "$APP" ]; then
    echo "ERRO: $APP não existe." >&2
    echo "Gere o bundle antes:  pyinstaller edgemd.spec --noconfirm --clean" >&2
    exit 1
fi

mkdir -p "$DESTINO"
SAIDA="$DESTINO/EdgeMD-${VERSAO}.dmg"

echo "==> Conferindo a declaração de tipos no Info.plist"
PLIST="$APP/Contents/Info.plist"
if ! /usr/libexec/PlistBuddy -c "Print :CFBundleDocumentTypes" "$PLIST" >/dev/null 2>&1; then
    # Sem isto o app abre, mas nunca aparece em "Abrir com" — falha silenciosa
    # que só se percebe quando alguém tenta abrir um .md pelo Finder.
    echo "ERRO: $PLIST não declara CFBundleDocumentTypes." >&2
    echo "O bundle precisa ser gerado pelo edgemd.spec do projeto." >&2
    exit 1
fi
echo "    ok"

# ---------------------------------------------------------------------------
# Assinatura ad-hoc
# ---------------------------------------------------------------------------
# Sem assinatura nenhuma, o macOS em Apple Silicon recusa executar o binário.
# A assinatura ad-hoc não substitui uma Developer ID, mas faz o app rodar em
# quem compilou.
echo "==> Assinando ad-hoc"
codesign --force --deep --sign - "$APP" 2>/dev/null || \
    echo "    AVISO: assinatura ad-hoc falhou; o app pode precisar de liberação manual"

# ---------------------------------------------------------------------------
# DMG
# ---------------------------------------------------------------------------
echo "==> Montando o DMG"
rm -f "$SAIDA"

# Uma pasta temporária com o .app e o atalho para /Applications: é o layout que
# deixa claro que basta arrastar.
ESTAGIO="$(mktemp -d)"
trap 'rm -rf "$ESTAGIO"' EXIT
cp -R "$APP" "$ESTAGIO/"
ln -s /Applications "$ESTAGIO/Aplicações"

hdiutil create \
    -volname "$VOLUME" \
    -srcfolder "$ESTAGIO" \
    -ov \
    -format UDZO \
    -fs HFS+ \
    "$SAIDA" >/dev/null

echo
echo "Pronto: $SAIDA"
echo
echo "Para instalar: abra o DMG e arraste o EdgeMD para Aplicativos."
echo "Na primeira execução, o macOS pode pedir para liberar em Ajustes →"
echo "Privacidade e Segurança, por não haver assinatura de desenvolvedor."
