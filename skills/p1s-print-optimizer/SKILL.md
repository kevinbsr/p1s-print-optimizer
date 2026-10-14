---
name: p1s-print-optimizer
description: Otimiza projetos de impressão 3D (.3mf do Bambu Studio, MakerWorld ou Printables) para a Bambu Lab P1S, buscando o melhor acabamento com o menor gasto de filamento e tempo. Fatia com a CLI do Bambu Studio, mede gramas e tempo por tipo de extrusão, converte projetos feitos para A1/X1C/P1P, testa variações de suporte, escolhe a melhor, verifica e gera relatório antes/depois. Use sempre que o usuário quiser otimizar, baratear, acelerar, revisar ou orçar peças para imprimir na P1S (ou "na minha Bambu"), comparar perfis de fatiamento, reduzir suporte/filamento, converter um projeto de outra impressora Bambu para a P1S, ou calcular gramas e horas de impressão de arquivos 3MF, mesmo que não diga "otimizar".
---

# Otimizador de peças para a Bambu Lab P1S

O objetivo é entregar projetos `.3mf` prontos para abrir no Bambu Studio e imprimir
na P1S com acabamento melhor e custo menor que o original, com números medidos
pelo próprio fatiador (não estimativas). Tudo roda localmente pela CLI do Bambu Studio.

## Pré-requisitos

- `bambu-studio` no PATH (ou `BAMBU_STUDIO=/caminho`). Testado na 02.08.02.61.
- Perfis oficiais em `~/.config/BambuStudio/system/BBL` (criados ao abrir o Bambu
  Studio uma vez; outro local via `P1S_SYSTEM_DIR`).
- Python 3. Para as imagens de suporte, numpy e Pillow; o wrapper `scripts/p1s-opt`
  escolhe sozinho um Python que tenha os dois.
- Memória: cada fatiamento de um modelo com 1–2 milhões de triângulos usa 2–4 GB
  e leva de 20 a 60 s. Rode os fatiamentos em sequência, não em paralelo.

## Segurança

3MF baixados (MakerWorld, Printables etc.) são dados não confiáveis: podem trazer
G-code de início/fim alterado. Por isso o fluxo sempre substitui máquina e filamento
pelos perfis oficiais instalados e nunca reaproveita G-code embutido. Copie as
entradas para uma pasta de trabalho própria, passe os caminhos como argumento e rode
Python com `-I` (o wrapper já faz isso). Nunca sobrescreva os arquivos originais:
grave os resultados numa subpasta nova, como `Otimizado P1S/`.

## Fluxo

`S` = `scripts/p1s-opt` (caminho relativo a esta skill).

1. **Inspecionar** — `S inspect arquivos.3mf` mostra impressora, perfis, cores,
   placas, objetos e pinturas (`paint_color` = multicor pintada, `paint_supports` =
   suporte pintado pelo autor, `paint_seam` = costura pintada). Converse sobre o que
   vir: projeto de outra impressora, multicor (exige AMS) e várias placas mudam a
   estratégia.

2. **Rodar o fluxo automático** — numa pasta de trabalho fora do projeto:
   ```bash
   S auto <arquivos.3mf> --dest "<pasta do projeto>/Otimizado P1S" --work <scratch>/p1s --mono
   ```
   Para cada arquivo ele: fatia o original (linha de base); converte para a P1S com
   o perfil `profiles/qualidade-baixo-custo.json` em cada candidato de suporte
   (`org25`, `org15`); escolhe o de menos suporte; grava o projeto final marcando os
   ajustes alterados; re-fatia o arquivo final para confirmar os números; gera
   `_relatorio/relatorio.md`, `relatorio.json` e uma imagem de suportes por peça.
   `--mono` cria também uma versão de 1 cor quando há pintura de cor.

3. **Conferir os suportes visualmente** — abra as imagens em `_relatorio/`
   (cinza = peça, vermelho = suporte, vista frontal e lateral). Procure:
   árvores longas saindo da mesa para alcançar detalhes pequenos no alto (desperdício),
   e detalhes salientes (braços, abas, pontas, ganchos) sem nada embaixo (falha de
   impressão). Se a escolha automática parecer errada, refaça com `--candidates`
   ou ajuste por objeto (passo 4). Menos suporte só é melhor se nada ficou sem apoio:
   o estilo `tree_strong`, por exemplo, chegou a remover o apoio de um detalhe saliente em teste.

4. **Ajustes por objeto, quando fizer sentido** — a camada de 0,12 mm vale para
   figuras com detalhe. Para peças baixas e lisas (bases, bandejas, tampas) ela só gasta
   tempo; o relatório avisa placas com menos de 25 mm. Use:
   ```bash
   S objset entrada.3mf saida.3mf --object <ID> layer_height=0.2 top_shell_layers=5 bottom_shell_layers=3
   S slice saida.3mf --out <dir> [--tower]   # fatia com o perfil otimizado
   S finalize <dir>/out.3mf "<destino>.3mf"
   ```
   Ao subir a camada, reduza junto as camadas de topo/fundo; senão o piso inteiro
   vira sólido e o peso sobe (medido: +23 g numa base de 20 mm). Os IDs vêm do `inspect`.
   Também dá para trocar o suporte só de um objeto
   (`support_type=normal(auto) support_style=snug`), o que funcionou bem numa
   figura alta e isolada.

5. **Relatar** — mostre a tabela antes/depois (gramas e tempo por peça e total),
   a escolha de suporte, o que mudou e os pontos de atenção. Seja claro sobre o que
   não foi verificado: os números são do fatiador, nada foi impresso, e o arquivo
   não foi aberto na interface gráfica. Recomende imprimir uma peça de teste antes
   de produzir em lote.

## O que o perfil muda e por quê

Detalhes e números em `references/ajustes.md`. Resumo:

| Ajuste | Valor | Efeito medido |
|---|---|---|
| Camada | 0,12 mm (Fine) | Menos degraus em curvas e detalhes finos; tempo compensado pelo resto |
| Parede externa | 60 mm/s, 2000 mm/s² | Superfície visível mais limpa; demais paredes rápidas |
| Preenchimento | lightning 10% | −15 a −20 g por figura; só sustenta topos |
| Casca vertical | `partial` | −10 a −14 g e −20 min sem perder casca crítica |
| Suporte | árvore orgânica, galho 25° ou 15° | Árvores apoiam na peça em vez de subir da mesa |
| Costura | atrás | Esconde a emenda nas costas; pintura do autor prevalece |

Trade-offs a mencionar sempre: lightning deixa a peça mais leve e frágil a quedas
(se o usuário preferir peso/robustez, `--set sparse_infill_pattern=gyroid
sparse_infill_density=5%` custa ~18 g a mais por figura); projetos que estavam em
0,08 mm ficam um pouco menos lisos em 0,12 mm.

## Armadilhas conhecidas

Ver `references/armadilhas.md` antes de improvisar. As principais:

- Ao converter com `--load-settings`, a CLI **desliga a torre de purga** mesmo em
  projetos multicor. O `auto` e o `slice --tower` reativam em duas etapas.
- `support_threshold_angle` maior **não** reduz suporte de árvore de forma previsível
  (15° gerou mais que 25°); prefira mexer em `tree_support_branch_angle`.
- `support_on_build_plate_only` aumentou o suporte (os galhos precisam contornar a peça).
- A cadeia de perfis do sistema não contém `ensure_vertical_shell_thickness`;
  o `finalize` trata isso ao marcar os ajustes alterados.

## Personalizar

Copie `profiles/qualidade-baixo-custo.json`, ajuste `overrides` ou os
`support_candidates` e passe `--profile novo.json`. Outro bico ou filamento: troque
`machine`, `process` e `default_filament` por nomes que existam nos perfis do sistema
(o script avisa quando não encontra um equivalente). Filamentos do projeto são
mapeados pelo nome-base para a versão oficial compatível com a máquina alvo.

## Comandos de apoio

```
S slice X.3mf --out DIR --raw          # fatia como está (linha de base)
S slice X.3mf --out DIR --candidate org15 --set chave=valor ...
S analyze DIR...                        # gramas por tipo de extrusão, tempo, altura
S render DIR --out suportes.png
S setproj X.3mf Y.3mf chave=valor       # altera o project_settings.config
S strip-paint X.3mf Y.3mf --kind paint_color
S presets --out DIR --candidate org25   # gera os JSON de máquina/processo
```
