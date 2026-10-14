# Changelog

## 0.2.0 — 2026-10-14

- `auto` mantém o suporte desligado quando o original não usa suporte (peças
  articuladas); `--support auto|on|off`.
- `auto` testa também a camada original, com o processo oficial dela, e escolhe
  pelo custo (gramas + suporte + `--g-por-hora`); relatório com tabela de variantes
  e aviso quando o tempo sobe.
- Correção: gramas por tipo de extrusão contavam o avanço após cada retração,
  inflando os valores em 30–75%. Totais por placa não eram afetados.
- Entrada `.stl`, `.obj` e `.step`; peças maiores que a mesa são recusadas.
- Opções `--robusto` e `--set` no `auto`; `finalize` com saída legível.
- Atalho opcional para o Flea em `extras/flea/`.

## 0.1.0 — 2026-10-14

Primeira versão.

- Comandos `inspect`, `presets`, `slice`, `analyze`, `render`, `objset`, `setproj`,
  `strip-paint`, `finalize` e `auto`.
- Perfil `qualidade-baixo-custo` (0,12 mm, lightning, casca parcial, árvore
  orgânica, parede externa lenta) com candidatos de suporte `org25` e `org15`.
- Conversão de projetos A1/X1C/P1P para P1S com perfis oficiais e mapeamento de
  filamentos.
- Reativação da torre de purga em projetos multicor e versão de 1 cor opcional.
- Relatório antes/depois em Markdown e JSON, com verificação por re-fatiamento.
- Validado em 8 projetos de figuras decorativas: 793 g · 36h00 → 537 g · 31h14.
