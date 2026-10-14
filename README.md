# p1s-print-optimizer

Skill do Claude Code que otimiza projetos de impressão 3D para a **Bambu Lab P1S**:
melhor acabamento com menos filamento e tempo, usando a CLI do Bambu Studio para
medir cada decisão.

Num teste com 8 projetos de figuras decorativas, o conjunto
caiu de **793 g · 36h00** para **537 g · 31h14** (−32% de filamento, −13% de tempo),
com camada de 0,12 mm no lugar de 0,16/0,20 mm. Detalhes em
[`references/ajustes.md`](skills/p1s-print-optimizer/references/ajustes.md).

## O que faz

- Lê projetos `.3mf` (inclusive de A1, X1C, P1P) e mostra impressora, perfis,
  filamentos, placas e pinturas de cor/suporte/costura.
- Fatia o original como linha de base e mede gramas por tipo de extrusão
  (parede, preenchimento, suporte, torre…), tempo e altura de cada placa.
- Converte para a P1S com os perfis **oficiais** instalados, aplicando o perfil
  "qualidade com baixo custo", e testa variações de suporte.
- Escolhe a variação com menos suporte, grava o projeto final marcando no Bambu
  Studio o que foi alterado, re-fatia o arquivo final para confirmar os números e
  gera relatório (Markdown, JSON e imagens dos suportes).
- Opcionalmente cria uma versão de 1 cor de projetos multicor.
- Permite ajustes por objeto (camada mais alta em bases, outro tipo de suporte
  numa peça específica) sem abrir a interface gráfica.

## Instalação

```bash
git clone https://github.com/kevinbsr/p1s-print-optimizer.git
p1s-print-optimizer/install.sh
```

O `install.sh` cria o link `~/.claude/skills/p1s-print-optimizer` apontando para a
pasta da skill no repositório, então um `git pull` já atualiza a skill.

Requisitos: Bambu Studio (`bambu-studio` no PATH; testado na 02.08.02.61) aberto ao
menos uma vez para baixar os perfis do sistema, Python 3, e numpy + Pillow para as
imagens de suporte.

## Uso com o Claude Code

Peça em linguagem natural, por exemplo:

> Otimiza essas peças para imprimir na P1S, quero a melhor qualidade gastando pouco.

> Quanto filamento e tempo gastam esses 3MF na minha P1S? Dá para reduzir o suporte?

> Esse projeto é da A1, converte para a P1S.

## Uso direto pela linha de comando

```bash
S=skills/p1s-print-optimizer/scripts/p1s-opt

$S inspect peca.3mf
$S auto *.3mf --dest "Otimizado P1S" --work /tmp/p1s --mono
$S slice peca.3mf --out /tmp/p1s/x --candidate org15 --set outer_wall_speed=80
$S objset base.3mf base-mod.3mf --object 13 layer_height=0.2 top_shell_layers=5 bottom_shell_layers=3
$S finalize /tmp/p1s/x/out.3mf "Otimizado P1S/peca.3mf"
```

`$S --help` e `$S <comando> --help` listam todas as opções.

## Estrutura

```
skills/p1s-print-optimizer/
├── SKILL.md                         instruções que o Claude segue
├── scripts/
│   ├── p1s-opt                      wrapper (escolhe o Python, roda isolado)
│   └── p1s_opt.py                   todos os comandos
├── profiles/
│   └── qualidade-baixo-custo.json   perfil padrão e candidatos de suporte
└── references/
    ├── ajustes.md                   justificativa e medições de cada ajuste
    └── armadilhas.md                comportamentos inesperados da CLI
```

## Perfil padrão

Base `0.12mm Fine @BBL X1C` (o Bambu Studio usa os perfis X1C para a P1S) com:
casca vertical `partial`, preenchimento lightning 10%, suporte em árvore orgânica
(galho 25° ou 15°, o que gastar menos), parede externa a 60 mm/s e 2000 mm/s²,
costura atrás e gerador de paredes Arachne. Para criar um perfil próprio, copie o
JSON, altere `overrides` e passe `--profile`.

## Limites

- Os números são do fatiador; a skill não imprime nem abre a interface gráfica.
  Imprima uma peça de teste antes de produzir em lote.
- Preenchimento lightning deixa a peça mais leve e menos resistente a quedas.
- Aceita apenas projetos `.3mf`; para STL, importe no Bambu Studio e salve como projeto antes.
- Por segurança, máquina e filamento sempre vêm dos perfis oficiais; G-code
  personalizado embutido no 3MF original é descartado.

## Complementos

- [orcamento-impressao-3d](https://github.com/kevinbsr/orcamento-impressao-3d): transforma os projetos
  otimizados em orçamento e verifica se a licença do modelo permite vender as impressões.

## Licença

MIT. Ver [LICENSE](LICENSE).
