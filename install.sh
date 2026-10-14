#!/usr/bin/env bash
# Instala a skill no Claude Code criando um link para a pasta do repositório.
set -euo pipefail
repo="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
dest="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/p1s-print-optimizer"
mkdir -p "$(dirname "$dest")"
if [ -e "$dest" ] && [ ! -L "$dest" ]; then
  echo "Já existe uma pasta em $dest (não é link). Remova ou renomeie antes." >&2
  exit 1
fi
ln -sfn "$repo/skills/p1s-print-optimizer" "$dest"
echo "Skill instalada: $dest -> $repo/skills/p1s-print-optimizer"
command -v bambu-studio >/dev/null || echo "Aviso: bambu-studio não está no PATH (ou defina BAMBU_STUDIO)." >&2
[ -d "${P1S_SYSTEM_DIR:-$HOME/.config/BambuStudio/system/BBL}" ] || echo "Aviso: perfis do sistema não encontrados; abra o Bambu Studio uma vez." >&2
