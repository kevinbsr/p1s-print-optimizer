# Calibração da P1S

A fonte é `~/Documents/WERX/Calibração P1S/RESULTADOS.md`, que o Kevin também consulta.
Leia esse arquivo antes de mudar fluxo, ferro ou furos. Atualize-o lá, não aqui.

## Resumo (placa de testes de 10/11/2026, PLA azul Voolt3D, 0.20mm Standard)

- **Tempo:** 2h49 reais × 2h41 previstos pela impressora (2h53 no fatiador). A previsão é confiável.
- **Medidas externas:** X 19,99, Y 19,94, Z 20,10 mm. Não compensar.
- **Fluxo:** o padrão (0,98) está certo.
  - No passo 1, ficaram bons os quadrados de 97% a 103%, com o centro em 100%.
  - No cartão, tudo de 0.90 a 1.04 ficou muito bom.
- **Ferro:** todos os do cartão ficaram excelentes. Mantenha o 60/20 dos chaveiros v3, já validado em produção.
- **Furos verticais:** saem ~0,23 mm menores no diâmetro (8→7,87; 6→5,77; 5→4,66; 3→2,73).
  - Para furo de encaixe, some +0,2 mm (≥6 mm) ou +0,3 mm (≤5 mm),
  - ou use `--set xy_hole_compensation=0.1`.
  - O rebaixo de 10,3 mm para o ímã de 10 × 2 mm funciona.
- **Fiapos:** muitos no torture test (cone, pinos, paredes finas). Na A2L, com outro filamento Voolt3D,
  aconteceu o mesmo. A causa provável é o perfil Bambu PLA Basic (220 °C) com filamento Voolt3D.
  Próximo passo: torre de temperatura de 215 a 195 °C. Secar o rolo antes de peça de cliente.
- **Balanço curvo:** a borda do arco saiu áspera e um pouco levantada. Peças com balanço longo
  precisam de suporte ou de outra orientação.

## Comparação com a A2L

| | P1S | A2L |
|---|---|---|
| Furos, perda média | −0,23 mm | −0,28 mm |
| Fluxo | 0,98 serve | pede ~1.04 |
| Ferro | 60/20 | 60/30 |

Ao converter uma peça de encaixe da A2L para a P1S, o furo pode ficar uns 0,05 mm mais folgado.
