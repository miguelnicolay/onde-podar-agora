# Dados limpos

Versões limpas dos dados que estão neste repositório. Os arquivos originais, em `dados/` e `codigo/dados_entrada/`, **não foram alterados**, porque o site usa eles.

Para refazer tudo, rode da raiz do repositório:

```
python codigo/limpeza/limpar_dados.py
```

Só precisa de pandas e numpy. Cada valor alterado nos rankings e no Open-Meteo fica em `registro_limpeza.csv`, com o valor original, o novo e a regra. As contagens ficam em `resumo_limpeza.json`.

## Arquivos

| Arquivo | Linhas | Vem de | O que mudou |
| --- | --- | --- | --- |
| `ranking_ceps_poda_limpo.csv` | 9.848 | `dados/ranking_ceps_poda.csv` | 12 coordenadas estimadas, 48 CEPs com bairro, região e zona preenchidos, 1 zona corrigida, 14 nomes de região padronizados; 4 colunas novas |
| `ranking_areas_150m_limpo.csv` | 5.384 | `dados/ranking_areas_150m.csv` | nomes de ação iguais aos do ranking por CEP; bairro, zona e coordenada copiados do CEP limpo |
| `clima_diario_rio_openmeteo_limpo.csv` | 1.512 | `codigo/dados_entrada/clima_diario_rio_openmeteo.csv` | 1 dia com 25 horas de chuva passou a 24 |
| `chuva_estacoes_diaria_limpa.csv` | 90.375 | `codigo/dados_entrada/clima_estacoes_rio.zip` | as 5 tabelas de pluviômetros numa só, sem a sobreposição do Alerta Rio, com marcações de qualidade |
| `estacoes_pluviometricas.csv` | 154 | o mesmo zip | cadastro único das estações das 4 redes, com período e dias confiáveis |
| `registro_limpeza.csv` | 283 | — | cada valor alterado |
| `resumo_limpeza.json` | — | — | contagens de cada regra |

## Regras

### Rankings

- **R1. Coordenada impossível.** Vale para o CEP fora do município (5 casos, um deles no Espírito Santo) e para o CEP sem bairro a mais de 5 km dos outros CEPs do mesmo prefixo (7 casos). Esses últimos estavam quase todos no mesmo ponto do Centro, com cara de ponto padrão do geocodificador. Nos dois casos, a coordenada passa a ser a mediana dos outros CEPs com os mesmos 5 primeiros dígitos. A coluna `coordenada_estimada` marca os 12 casos.
- **R2. Sem bairro, região ou zona (48 CEPs).** O bairro passa a ser o mais comum entre os 5 CEPs mais próximos. A região e a zona vêm desse bairro. Só se aplica quando o CEP mais próximo está a até 2 km. A coluna `local_preenchido` marca esses casos.
- **R3. Bairro em duas zonas.** Um CEP do Alto da Boa Vista estava na Zona Sul; passou para a Tijuca/Grande Tijuca, como os outros 31 do bairro.
- **R4. Nome de região.** "COMPLEXO DO ALEMÃO" passou a "COMPLEXO DO ALEMAO", sem acento como as outras.
- **R5. Nomes de ação nas áreas.** "COMLURB pode ir já" passou a "COMLURB pode ir", "Precisa da Light" a "Depende da Light" e "COMLURB + Light" a "COMLURB + agendar Light". Muda só o nome: a classificação de cada área continua a mesma.
- **R6. Áreas.** Bairro e zona vazios são copiados do CEP de maior nota, já limpo. Nas áreas de um só CEP com coordenada estimada, a coordenada da área acompanha a do CEP.
- **R13. CEP suspeito (só marcação).** `dist_km_ao_prefixo` é a distância até a mediana dos CEPs com o mesmo prefixo. `cep_suspeito` = mais de 5 km. São **641 CEPs (6,5%)**, 27 deles entre os 500 primeiros do ranking. Exemplo: o 23535-430, de Santa Cruz, aparece no Maracanã na posição 63. Ou o CEP atribuído ou a localização está errado, e o arquivo não permite saber qual. Por isso nada foi alterado. A conferência precisa dos chamados originais.

### Clima da cidade (Open-Meteo)

- **R7.** `chuva_hora_max` acima de 24 passa a 24 (1 dia).

### Pluviômetros

Uma linha por rede, estação e dia, de 01/08/2022 a 17/12/2024.

| Coluna | O que é |
| --- | --- |
| `chuva_dia_mm` | total do dia (vazio no Cemaden, que só tem o máximo em 1 h) |
| `chuva_max_15min_mm`, `chuva_max_1h_mm` | maior chuva em 15 min e em 1 h |
| `n_registros`, `medicoes_esperadas`, `cobertura` | medições do dia, medições esperadas e a razão entre elas |
| `dia_completo` | cobertura de 90% a 100% |
| `valor_suspeito`, `motivo_suspeito` | valor impossível ou leitura travada |
| `usar_total_dia` | o total do dia pode ser usado: dia completo, sem suspeita e de rede com total confiável |
| `tabela_origem` | tabela do BigQuery de onde veio a linha |

- **R8. Alerta Rio.** A tabela `taxa_precipitacao_alertario` entra até 02/06/2024 e a `taxa_precipitacao_alertario_5min` a partir de 03/06/2024. De 07/02 a 02/06/2024 as duas têm os mesmos dados; fica só uma. A primeira tabela passou a gravar a cada 5 minutos em 07/02/2024, então espera 96 medições por dia antes dessa data e 288 depois.
- **R9. Medições esperadas nas outras redes.** INEA = 96 por dia; Cemaden = 24 (uma por hora). Na WebSirene, que muda de ritmo (cerca de 64 por dia até 2023 e 96 em 2024), vale o número mais comum entre as estações em cada mês.
- **R10. Valores suspeitos.** Mais de 300 mm no dia, mais de 200 mm em 1 h, mais de 100 mm em 15 min, ou leitura da WebSirene travada em exatamente 60,0 mm em 15 min. São 29 dias-estação. O pior é a estação 8 do Alerta Rio em 17/02/2024: 2.686,8 mm no dia e 1.049,2 mm em 1 h.
- **R11. Total do dia da WebSirene não é usado.** Nos mesmos dias, o total dela é de 40% a 70% do total do Alerta Rio, e em cerca de 10% dos dias o máximo em 1 h passa do total do dia. Os máximos em 15 min e em 1 h continuam na tabela.
- **R12. Estações sem coordenada.** 5 estações (4 do Alerta Rio e 1 do Cemaden) não têm latitude nem longitude no cadastro, e nenhuma delas tem dados no período.

| Rede | Dias-estação | Dias completos | Suspeitos | Total do dia utilizável |
| --- | --- | --- | --- | --- |
| Alerta Rio | 26.470 | 89,8% | 13 | 23.662 |
| WebSirene | 61.101 | 54,0% | 16 | 0 (R11) |
| Cemaden | 2.687 | 55,7% | 0 | 0 (sem total do dia) |
| INEA | 117 | 88,9% | 0 | 102 |

## O que não foi limpo

- Os 4 CSVs de chamados e o de setores censitários, que não estão no repositório.
- As áreas de 150 m dos CEPs com coordenada estimada não foram recalculadas: isso exige rodar o pipeline.
- `quedas_verao_quadrados_1km.csv` não tinha problemas encontrados (nenhum quadrado repetido) e não foi copiado.
