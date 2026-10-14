# Ajustes do perfil e medições

Todos os números abaixo vieram do Bambu Studio 02.08.02.61 (CLI), PLA, bico
0,4 mm, em 8 projetos de figuras decorativas com base (120–190 mm de altura,
malhas de 1–2 milhões de triângulos). Primeiro foi medido um ajuste por vez na
peça G (base: 102,0 g · 3h40, camada 0,16 mm) e depois o conjunto.

## Efeito isolado de cada ajuste (peça G)

| Variação | Peso | Tempo | Observação |
|---|---|---|---|
| Original (0,16 Optimal, gyroid 5%, organic) | 102,0 g | 3h40 | suporte 19,8 g, casca flutuante 17,4 g |
| `ensure_vertical_shell_thickness=partial` | 92,2 g | 3h18 | casca flutuante 17,4 → 3,0 g |
| lightning 10% | 84,6 g | 3h18 | preenchimento 22,3 → 3,4 g |
| adaptive cubic 5% | 98,1 g | 3h33 | ganho pequeno |
| `support_threshold_angle=15` | 105,1 g | 3h50 | **mais** suporte (25,6 g) |
| `support_on_build_plate_only=1` | 102,6 g | 3h46 | mais suporte (22,9 g) |
| parede externa 60 mm/s + perfil HQ | 102,0 g | 4h47 | só tempo |
| estilo `tree_slim` / `tree_hybrid` | 91,3 g | 3h19 | suporte 6,2 g |
| `normal(auto)` + `snug` | 91,6 g | 3h21 | suporte 5,4 g |
| organic com galho a 25° | 90,0 g | 3h14 | suporte 3,3 g, galhos apoiados na própria peça |
| `tree_strong` | 90,5 g | 3h16 | suporte 3,4 g, mas em outra peça deixou um detalhe saliente sem apoio |

## Perfis combinados (peça G)

| Perfil | Peso | Tempo |
|---|---|---|
| 0,16 + todos os ajustes, parede externa 60 | 62,4 g | 2h58 |
| 0,16 + todos os ajustes, parede externa 120 | 62,4 g | 2h36 |
| 0,16 + todos os ajustes, mas gyroid 5% | 80,2 g | 3h23 |
| **0,12 + todos os ajustes (perfil padrão)** | **59,2 g** | **3h33** |

Conclusão: com os cortes de material, a camada de 0,12 mm e a parede externa lenta
cabem no mesmo tempo do original. A camada fina reduz os degraus em superfícies
curvas e detalhes pequenos; a parede externa lenta reduz ondulação (ringing) na
superfície visível.

## Resultado no conjunto (8 projetos)

| Peça | Antes | Depois |
|---|---|---|
| A | 82,6 g · 3h00 | 53,3 g · 3h15 |
| B | 86,8 g · 3h02 | 50,3 g · 3h17 |
| C | 65,3 g · 1h47 | 43,9 g · 2h24 |
| D (3 placas, ajuste por objeto) | 158,3 g · 6h36 | 135,7 g · 5h46 |
| E | 82,9 g · 4h24 | 57,0 g · 3h45 |
| F (original em 0,08 mm) | 74,5 g · 4h58 | 51,7 g · 3h19 |
| G | 102,0 g · 3h40 | 59,2 g · 3h33 |
| H (2 cores, projeto de A1) | 140,9 g · 8h32 | 86,1 g · 5h55 |
| **Total** | **793 g · 36h00** | **537 g · 31h14** |

Versão de 1 cor da peça H: 66,8 g · 4h21. A segunda cor usava 0,5 g de filamento,
mas exigia 22 g de torre de purga e 46 trocas.

## Suporte: qual ângulo de galho

Nenhum valor ganhou sempre. Com galho a 15° as árvores ficam mais verticais e
pousam na própria peça; a 25° às vezes contornam melhor.

| Peça | galho 25° | galho 15° |
|---|---|---|
| A | 6,2 g | 6,6 g |
| B | 25,6 g | 4,3 g |
| C | 5,3 g | 1,8 g |
| E | 11,5 g | 16,7 g |
| F | 6,9 g | 7,0 g |
| G | 4,2 g | 6,1 g |
| H | 14,7 g | 13,0 g |

Por isso o `auto` fatia os dois e fica com o menor. O estilo orgânico não deixou de
apoiar nenhum detalhe nos testes; ele só muda o caminho dos galhos. Mesmo assim,
confira as imagens.

## Peças baixas

Numa base lisa de 20 mm de altura, 0,12 mm levou 4h30 contra 3h14 em 0,20 mm.
Subir a camada sem reduzir as camadas de topo/fundo deixou o piso todo sólido
(120,6 g); com `top_shell_layers=5 bottom_shell_layers=3` por objeto ficou em
105,1 g. Vale a troca de ~8 g por 1h16 de máquina.
