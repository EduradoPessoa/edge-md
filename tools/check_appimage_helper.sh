#!/usr/bin/env bash
# Verifica que buscar_appimagetool devolve APENAS o caminho em stdout.
#
# O bug que isto previne: com a mensagem de progresso em stdout, a substituicao
# de comando FERRAMENTA="$(buscar_appimagetool)" capturava duas linhas, e o
# bash tentava executar "==> Baixando o appimagetool" (exit 127).
set -euo pipefail

SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../packaging/linux/build_appimage.sh"

# Extrai so a funcao, sem executar o resto do script.
funcao="$(sed -n '/^buscar_appimagetool()/,/^}/p' "$SCRIPT")"

if [ -z "$funcao" ]; then
    echo "FALHA: nao consegui extrair buscar_appimagetool"
    exit 1
fi

DESTINO="$(mktemp -d)"
trap 'rm -rf "$DESTINO"' EXIT

# appimagetool falso, ja "instalado": a funcao deve devolver o caminho sem
# baixar nada.
printf '#!/bin/sh\necho falso\n' > "$DESTINO/appimagetool"
chmod +x "$DESTINO/appimagetool"

saida="$(bash -c "set -euo pipefail; DESTINO='$DESTINO'; $funcao; buscar_appimagetool")"
linhas="$(printf '%s' "$saida" | wc -l)"

echo "  stdout: '$saida'"
echo "  linhas: $((linhas + 1))"

if [ "$(printf '%s' "$saida" | wc -l)" -ne 0 ]; then
    echo "FALHA: stdout tem mais de uma linha — a mensagem de progresso vazou"
    exit 1
fi

if [ "$saida" != "$DESTINO/appimagetool" ]; then
    echo "FALHA: esperado $DESTINO/appimagetool, veio '$saida'"
    exit 1
fi

echo "  OK: a funcao devolve so o caminho"
