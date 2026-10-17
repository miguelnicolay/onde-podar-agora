"""
Viés de registro por zona no ranking "Onde podar agora".

Usa só o arquivo público dados/ranking_ceps_poda.csv (nota de 20/09/2026).
Compara a parte de cada zona nas quedas e chamados de risco dos últimos 12 meses
com a parte de cada zona no topo do ranking, e testa uma variante da nota em que
o sinal "travado na Light" é corrigido pela taxa de Pendente de cada zona.

Uso (da pasta codigo/): python analises/vies_por_zona_publico.py ../dados/ranking_ceps_poda.csv

Não precisa dos CSVs de chamados: roda só com o ranking publicado. O teste com as 8 datas
de corte, que mostra se a correção acerta mais o futuro, está na etapa K01.
"""
import os, sys
import numpy as np
import pandas as pd

d = pd.read_csv(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'dados', 'ranking_ceps_poda.csv'))
PESOS = dict(risco=25, comlurb=15, light=40, previsao=10, espera=10)

# 1) A nota publicada é reproduzida a partir dos pontos de cada sinal?
recalc = sum(PESOS[k] * d[f'pts_{k}_0a1'] for k in PESOS)
print('Diferença máxima entre nota publicada e recalculada:', round((recalc - d.nota_0a100).abs().max(), 2))

# 2) Parte de cada zona: CEPs, quedas, risco, pedidos na Light e lugares no topo
z = d.groupby('zona').agg(ceps=('cep', 'size'), quedas_12m=('quedas_12m', 'sum'),
                          risco_12m=('risco_queda_remocao_12m', 'sum'),
                          light=('pedidos_travados_light', 'sum'))
ordem = d.sort_values('posicao')
for n in (200, 500):
    z[f'top{n}'] = ordem.head(n).zona.value_counts()
z = z.fillna(0)
parte = (z / z.sum() * 100).round(1)
parte.columns = [c + ' (%)' for c in parte.columns]
print('\nParte de cada zona (%):'); print(parte.to_string())
print('\nPedidos travados na Light para cada queda nos últimos 12 meses:')
print((z.light / z.quedas_12m).round(1).to_string())

# 3) Variante: o sinal da Light corrigido pela zona.
#    Cada zona usa o status Pendente numa proporção diferente (ex.: Oeste quase não usa).
#    Aqui, os pedidos na Light de cada CEP são multiplicados por (taxa da cidade / taxa da zona),
#    com a taxa = pedidos na Light por queda nos últimos 12 meses. É uma correção simples,
#    só para medir o tamanho do efeito; precisa ser validada com os dados completos.
taxa = z.light / z.quedas_12m
fator = (z.light.sum() / z.quedas_12m.sum()) / taxa
light_aj = d.pedidos_travados_light.fillna(0) * d.zona.map(fator).fillna(1)  # zona não identificada: sem correção
pts_light_aj = np.minimum(1, np.log1p(light_aj) / np.log1p(12))
d['nota_corrigida'] = d.nota_0a100 - PESOS['light'] * d.pts_light_0a1 + PESOS['light'] * pts_light_aj
d['posicao_corrigida'] = d.nota_corrigida.rank(ascending=False, method='first').astype(int)
comp = pd.DataFrame({
    'top200 atual (%)': ordem.head(200).zona.value_counts(normalize=True) * 100,
    'top200 corrigido (%)': d.nsmallest(200, 'posicao_corrigida').zona.value_counts(normalize=True) * 100,
    'quedas 12m (%)': z.quedas_12m / z.quedas_12m.sum() * 100,
}).fillna(0).round(1)
print('\nTop 200: nota atual x nota com a Light corrigida por zona'); print(comp.to_string())
mantidos = len(set(ordem.head(200).cep) & set(d.nsmallest(200, 'posicao_corrigida').cep))
print(f'\nCEPs que continuam no top 200: {mantidos} de 200')

d[['cep', 'logradouro_ref', 'bairro', 'zona', 'posicao', 'nota_0a100', 'posicao_corrigida', 'nota_corrigida']] \
    .sort_values('posicao_corrigida').to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ranking_com_light_corrigida.csv'), index=False, encoding='utf-8-sig')
print('\nGravado: ranking_com_light_corrigida.csv')
