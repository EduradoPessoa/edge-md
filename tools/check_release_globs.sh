#!/usr/bin/env bash
# Testa os padroes de glob do job de publicacao contra uma arvore de exemplo.
#
# Existe porque o softprops/action-gh-release nao falha quando o glob nao casa
# nada: ele publica uma Release sem anexo e reporta sucesso. A primeira tag
# v0.1.0 saiu vazia por causa de um "dist/" a mais no caminho.
#
# A verificacao que importa e sobre a UNIAO dos padroes: ela precisa casar
# exatamente os quatro instaladores, nem menos (Release incompleta) nem mais (o
# bundle solto do Windows entraria, com centenas de MB que o instalador ja
# contem).
set -euo pipefail

BASE="$(mktemp -d)"
trap 'rm -rf "$BASE"' EXIT

# Reproduz o que o download-artifact entrega, conforme verificado na execucao
# 35510873130: os caminhos perdem o prefixo dist/.
mkdir -p "$BASE/artefatos/EdgeMD-windows/installer"
mkdir -p "$BASE/artefatos/EdgeMD-windows/edgemd/_internal"
mkdir -p "$BASE/artefatos/EdgeMD-windows/edgemd/PyQt6/Qt6/plugins"
mkdir -p "$BASE/artefatos/EdgeMD-msix/arvore/edgemd"
mkdir -p "$BASE/artefatos/EdgeMD-linux"
mkdir -p "$BASE/artefatos/EdgeMD-macos"

# Os instaladores publicados.
touch "$BASE/artefatos/EdgeMD-windows/installer/EdgeMD-0.1.0-setup.exe"
touch "$BASE/artefatos/EdgeMD-msix/EdgeMD-0.1.0-x64.msix"
touch "$BASE/artefatos/EdgeMD-msix/EdgeMD-dev.cer"
touch "$BASE/artefatos/EdgeMD-linux/edgemd_0.1.0_amd64.deb"
touch "$BASE/artefatos/EdgeMD-linux/EdgeMD-0.1.0-x86_64.AppImage"
touch "$BASE/artefatos/EdgeMD-macos/EdgeMD-0.1.0.dmg"

# Ruido que NAO pode entrar na Release.
touch "$BASE/artefatos/EdgeMD-windows/edgemd/edgemd.exe"
touch "$BASE/artefatos/EdgeMD-windows/edgemd/QtWebEngineProcess.exe"
touch "$BASE/artefatos/EdgeMD-windows/edgemd/PyQt6/Qt6/plugins/qwindows.dll"
# A arvore do MSIX tem o bundle inteiro; so o pacote e o certificado interessam.
touch "$BASE/artefatos/EdgeMD-msix/arvore/edgemd/edgemd.exe"
touch "$BASE/artefatos/EdgeMD-msix/EdgeMD-dev.pfx"

cd "$BASE"
shopt -s nullglob

# Os mesmos padroes do .github/workflows/release.yml. Se mudarem la, mudam aqui.
PADROES=(
  "artefatos/EdgeMD-windows/installer/*.exe"
  "artefatos/EdgeMD-msix/*.msix"
  "artefatos/EdgeMD-msix/*.cer"
  "artefatos/EdgeMD-linux/*.deb"
  "artefatos/EdgeMD-linux/*.AppImage"
  "artefatos/EdgeMD-macos/*.dmg"
)

# Quantos arquivos a uniao deve casar. O .pfx fica de fora de proposito: ele
# tem a chave privada do certificado de desenvolvimento e nao deve ser
# publicado, ainda que seja de teste.
ESPERADO=6

falhas=0

echo "  cada padrão precisa casar ao menos um arquivo:"
for padrao in "${PADROES[@]}"; do
    arquivos=( $padrao )
    if [ "${#arquivos[@]}" -eq 0 ]; then
        echo "    FALHA: nada casa $padrao"
        falhas=$((falhas + 1))
    else
        echo "    ok (${#arquivos[@]}): ${arquivos[*]}"
    fi
done

# Uniao dos padroes: e o conjunto que vai para a Release.
uniao=()
for padrao in "${PADROES[@]}"; do
    for arquivo in $padrao; do
        uniao+=( "$arquivo" )
    done
done

echo
echo "  união dos padrões (${#uniao[@]} arquivo(s)):"
for arquivo in "${uniao[@]}"; do
    echo "    $arquivo"
done

if [ "${#uniao[@]}" -ne "$ESPERADO" ]; then
    echo "    FALHA: esperado $ESPERADO arquivos, a união tem ${#uniao[@]}"
    falhas=$((falhas + 1))
fi

# Nada de bundle solto nem de chave privada na uniao.
for arquivo in "${uniao[@]}"; do
    case "$arquivo" in
        */arvore/*|*/edgemd/edgemd.exe|*QtWebEngineProcess*|*.dll)
            echo "    FALHA: o bundle solto entraria na Release: $arquivo"
            falhas=$((falhas + 1))
            ;;
        *.pfx)
            echo "    FALHA: a chave privada do certificado entraria na Release: $arquivo"
            falhas=$((falhas + 1))
            ;;
    esac
done

echo
if [ "$falhas" -gt 0 ]; then
    echo "  VEREDITO: $falhas problema(s)"
    exit 1
fi
echo "  VEREDITO: a união casa exatamente os $ESPERADO arquivos publicáveis"

