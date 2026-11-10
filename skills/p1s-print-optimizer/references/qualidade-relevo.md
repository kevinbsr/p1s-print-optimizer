# Qualidade em peças multicor com relevo (escudos, logos, plaquinhas)

Aprendido com a impressão de 2026-10-15: chaveiros de times numa P1S com bico de 0,4 mm.
Os discos têm 30 mm, com o escudo em relevo de 1,5 mm e cerca de 24 mm.
O Botafogo saiu limpo. O Vasco saiu com falhas, bolinhas e fiapos.

## Diagnóstico pelas fotos

> **Atenção (2026-10-15, à noite):** as correções desta tabela vieram de métricas do G-code e de
> raciocínio, sem impressão de teste. O disco do Fluminense impresso com elas (perfil `relevo-multicor`)
> saiu tão ruim quanto o Vasco: topos ásperos nas áreas pequenas e monograma quebrado. Trate as
> correções como hipóteses. A técnica mais usada pela comunidade é outra: escudo **embutido rente** e
> peça impressa **com a face para baixo**, com as cores nas primeiras camadas. Ela foi testada e
> descartada (ver "Confirmado em impressão").

| Sintoma na foto | Causa medida | Correção |
|---|---|---|
| Falhas e bolinhas nos detalhes (letras, cordame, casco) | 41 % do branco e 92 % do dourado do Vasco eram mais finos que 0,8 mm (2 linhas de bico). No G-code, o disco do Vasco tinha cerca de 400 trechos curtos, contra cerca de 200 no do Botafogo | Desenho: traços ≥ 0,8 mm (aceitável ≥ 0,4 mm) e ilhas ≥ 1 mm². Ou peça maior. Ou bico de 0,2 mm |
| Fiapos finos sobre o relevo | Até cerca de 700 recolhimentos numa camada (14 peças), com viagens cruzando o relevo, PLA genérico a 220 °C e filamento possivelmente úmido | Perfil `relevo-multicor` (`reduce_crossing_wall=1`), filamento seco, 5–10 °C a menos |
| Furos em áreas estreitas | Preenchimento de vãos a 250 mm/s em regiões de 0,5–1 mm | `gap_infill_speed=50` |
| Respingo de outra cor em peça de uma cor só | Aro preto na mesma placa de discos multicor: a troca de cor acontece com o aro já impresso ao lado | Peças de uma cor só em placa separada, ou na placa da mesma cor de fundo |

## Confirmado em impressão (Fluminense, 2026-10-16)

Placa com 4 discos iguais, face para cima, perfil padrão `0.20mm Standard @BBL X1C` e uma variação por disco:

| Disco | Variação | Resultado |
|---|---|---|
| 1 | padrão Bambu | campos ásperos, borda pontilhada (mesmo defeito de antes) |
| 2 | `ironing_type=topmost` | campos lisos |
| 3 | ironing + Arachne | campos lisos |
| 4 | ironing + `top_surface_line_width=0.3` | **melhor**, escolhido pelo usuário |

- O ferro só no topo resolveu os campos de cor. O monograma fino continuou ilegível em todos: isso é desenho, não fatiador.
- Escudo embutido com a face para baixo também foi impresso: melhor que o relevo sem ferro, mas com furos no
  branco e no verde e sem o relevo, que é o atrativo do produto. Descartado.
- Engrossar tudo por igual (buffer em todo o branco) fecha os vãos entre letras e vira mancha. Engrossar
  só os traços finos e preservar vãos de pelo menos 0,6 mm (`fonte/fat2.py`) mantém a leitura.
- Teste 3 (1 disco, monograma engrossado seletivamente para cerca de 0,9 mm): o melhor até agora. O usuário
  ajustou o ferro no Bambu Studio para todos os topos (`top`), fluxo 20 % e 60 mm/s. Esse é o perfil
  `relevo-multicor`. Ainda há pontos a melhorar, sem causa medida.
- Uma generalização do engrosso seletivo para escudos com várias cores de detalhe (Vasco) apagou a borda e
  embolou a caravela na prévia. Não use sem revisar.

## Regras de desenho para relevo multicor no bico de 0,4 mm

- Traço mínimo: 0,8 mm (2 linhas) para ficar bom; 0,4 mm sai como linha única, frágil.
  Abaixo de cerca de 0,35 mm o fatiador descarta.
- Ilha mínima: cerca de 1 mm². Ilhas menores saem como bolinha e somam recolhimentos e fiapos.
- Medir antes de fatiar: % da área de cada cor mais fina que 0,8 mm (abertura morfológica).
  Acima de cerca de 10 % numa cor, o resultado vai sair com falhas.
- Engrossar automaticamente funciona até certo ponto. No Vasco, fechar vãos de até 0,5 mm destruiu a
  caravela na prévia renderizada (não foi impresso) (o desenho é feito de linhas pretas finas). O meio-termo útil foi fechar vãos de 0,24 mm,
  engrossar 0,12 mm e descartar ilhas de 0,3 mm². Isso preserva o desenho, mas melhora pouco no G-code.
  Para escudos desse nível de detalhe, a solução real é peça maior, bico de 0,2 mm ou desenho simplificado à mão.

## Bico de 0,2 mm (medido: 4 discos do Vasco)

| Bico | Camada | Tempo | Filamento | Trocas |
|---|---|---|---|---|
| 0,4 mm | 0,20 | 1h24 | 19,1 g | 21 |
| 0,2 mm | 0,12 | 4h22 | 23,5 g | 36 |

Vale para lotes pequenos de peças com detalhe fino. Não troque de bico para peças simples.
Perfis: `Bambu Lab P1S 0.2 nozzle`, `0.12mm Standard @BBL X1C 0.2 nozzle`,
`Bambu PLA Basic @BBL X1C 0.2 nozzle`.

## Métricas de qualidade no `analyze`

O `analyze` agora mostra, por placa, os números abaixo e avisa quando passam dos limites:

- trocas de cor e quantas camadas têm troca;
- recolhimentos por camada (pico);
- trechos curtos por camada (pico, < 3,75 × bico);
- número de peças.

Limites por peça, calibrados nesta impressão:

| Situação | Trechos curtos por peça e camada | Recolhimentos por peça e camada |
|---|---|---|
| Aros lisos | cerca de 6 | cerca de 16 |
| Escudos que saíram com defeito | 60–140 | 50–140 |
| Limite do aviso | 40 | 40 |

O aviso de trechos curtos vale só para bico ≥ 0,4 mm. No 0,2 mm os detalhes finos são
impressos de verdade e geram muitos trechos curtos sem defeito.

## O que não funcionou (medido)

- `filter_out_gap_fill=1`: não mudou a contagem de trechos nem de recolhimentos.
- `ironing_type=top`: alisa o topo, mas em relevo com muitas ilhas somou cerca de 390 recolhimentos na
  última camada e cerca de 30 min. Use só em peças com topo amplo e poucas ilhas.
- `wall_loops=2` nos discos: economiza cerca de 5 g por placa, mas não reduz trechos curtos.
