#!/usr/bin/env bash
# Instala o atalho do Flea (botão direito → Run script → Otimizar para P1S). O processo
# de trabalho é um link para o repositório, então um `git pull` também o atualiza.
set -euo pipefail
here="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
bin="$HOME/.local/bin"
scripts="${XDG_CONFIG_HOME:-$HOME/.config}/flea/scripts"
mkdir -p "$bin" "$scripts"
ln -sfn "$here/p1s-otimizar" "$bin/p1s-otimizar"
# O Flea lista só arquivos regulares (find -type f): as entradas são cópias. Elas apenas
# chamam o p1s-otimizar, que é link e acompanha o repositório.
for f in "$here/scripts/"*; do
  rm -f "$scripts/$(basename "$f")"
  install -m 755 "$f" "$scripts/$(basename "$f")"
done
echo "Atalho instalado: $bin/p1s-otimizar e $(ls "$here/scripts" | wc -l) entrada(s) em $scripts"
command -v notify-send >/dev/null || echo "Aviso: notify-send ausente; não haverá notificações." >&2
command -v systemd-run >/dev/null || echo "Aviso: systemd-run ausente; o atalho precisa dele." >&2
