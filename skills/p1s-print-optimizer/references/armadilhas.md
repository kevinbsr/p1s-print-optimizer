# Armadilhas da CLI do Bambu Studio

Comportamentos observados na 02.08.02.61 que custaram tempo para descobrir.

## Conversão desliga a torre de purga

Ao carregar perfis com `--load-settings`/`--load-filaments`, o log mostra
`disable_wipe_tower_after_mapping: disable prime tower for only one filament!`
mesmo em projetos com pintura de cor. Sem torre, cada troca de cor sai sem
preparação e pode deixar borrões. Solução (feita por `auto` e `slice --tower`):

1. converter sem fatiar (`--export-3mf` sem `--slice`);
2. gravar `enable_prime_tower=1` no `project_settings.config`;
3. fatiar o resultado sem `--load-settings`.

## Avisos que podem ser ignorados

- `can not find system preset file: .../machine_full/...json` — a CLI procura perfis
  "achatados" que não vêm no pacote; os valores do próprio 3MF são usados.
- `ZFiller: both point in subject` — ruído do gerador de preenchimento.
- `old printable size {256,256,256} is larger than new printable size {256,256,250}` —
  ao converter da A1; só importa se a peça tiver mais de 250 mm de altura.
- `Influence area could not be increased!` — gerador de árvore; não indica falha.

## Suporte se comporta ao contrário do esperado

- Diminuir `support_threshold_angle` (25 → 15) **aumentou** o suporte de árvore.
- `support_on_build_plate_only=1` também aumentou: os galhos precisam contornar a
  peça até a mesa.
- `support_style=default` com `tree(auto)` resulta em orgânico.
- `tree_strong` gerou quase nada (0,3 g) numa peça e deixou um detalhe saliente sem apoio.

Mexa em `tree_support_branch_angle` e confira sempre a imagem.

## Pinturas do autor prevalecem

Suportes pintados (`paint_supports`) e costuras pintadas (`paint_seam`) continuam
valendo após a conversão. Se o autor pintou suporte desnecessário, remova com
`strip-paint --kind paint_supports` e compare.

## `different_settings_to_system`

A CLI marca como "do sistema" tudo que veio no JSON de processo, então o Bambu
Studio não mostraria os ajustes como modificados. O `finalize` recalcula a lista
comparando com o perfil oficial. `ensure_vertical_shell_thickness` não existe na
cadeia de herança do sistema (padrão implícito `enabled`) e é tratado à parte.

## Camada por objeto

`layer_height` por objeto não ajusta `top_shell_layers`/`bottom_shell_layers`.
Com camadas de 0,12 (7 topo/5 fundo) aplicadas a um objeto em 0,20, o piso vira
sólido. Grave as três chaves juntas.

## Python e dependências

Com mise/pyenv o `python3` do PATH pode não ter numpy e Pillow. O wrapper
`scripts/p1s-opt` testa `/usr/bin/python3` primeiro. Os demais comandos usam só a
biblioteca padrão.

## Formato do cabeçalho do G-code

`; filament_density: 1.26` usa dois-pontos no cabeçalho e `=` no bloco de
configuração no fim do arquivo. O analisador aceita os dois.
