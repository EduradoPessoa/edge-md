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
mkdir -p "$BASE/artefatos/EdgeMD-linux"
mkdir -p "$BASE/artefatos/EdgeMD-macos"

# Os quatro instaladores.
touch "$BASE/artefatos/EdgeMD-windows/installer/EdgeMD-0.1.0-setup.exe"
touch "$BASE/artefatos/EdgeMD-linux/edgemd_0.1.0_amd64.deb"
touch "$BASE/artefatos/EdgeMD-linux/EdgeMD-0.1.0-x86_64.AppImage"
touch "$BASE/artefatos/EdgeMD-macos/EdgeMD-0.1.0.dmg"

# Ruido que NAO pode entrar na Release.
touch "$BASE/artefatos/EdgeMD-windows/edgemd/edgemd.exe"
touch "$BASE/artefatos/EdgeMD-windows/edgemd/QtWebEngineProcess.exe"
touch "$BASE/artefatos/EdgeMD-windows/edgemd/PyQt6/Qt6/plugins/qwindows.dll"

cd "$BASE"
shopt -s nullglob

# Os mesmos padroes do .github/workflows/release.yml. Se mudarem la, mudam aqui.
PADROES=(
  "artefatos/EdgeMD-windows/installer/*.exe"
  "artefatos/EdgeMD-linux/*.deb"
  "artefatos/EdgeMD-linux/*.AppImage"
  "artefatos/EdgeMD-macos/*.dmg"
)

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

if [ "${#uniao[@]}" -ne 4 ]; then
    echo "    FALHA: esperado 4 arquivos, a união tem ${#uniao[@]}"
    falhas=$((falhas + 1))
fi

# Nenhum arquivo do bundle solto pode aparecer na uniao.
for arquivo in "${uniao[@]}"; do
    case "$arquivo" in
        */edgemd/*|*QtWebEngineProcess*|*.dll)
            echo "    FALHA: o bundle solto entraria na Release: $arquivo"
            falhas=$((falhas + 1))
            ;;
    esac
done

echo
if [ "$falhas" -gt 0 ]; then
    echo "  VEREDITO: $falhas problema(s)"
    exit 1
fi
echo "  VEREDITO: a união casa exatamente os quatro instaladores"
