"""
Ranking "Onde podar agora" · K01 — Viés de registro por zona: teste de uma nota corrigida
Tipo: exploratório

O que faz:
    A nota dá peso 40 ao sinal "travado na Light" (status Pendente), mas cada zona usa esse
    status numa proporção muito diferente: na Zona Oeste há cerca de 1,7 pedido Pendente para
    cada árvore caída nos últimos 12 meses; na Zona Norte, 6,7. Com a nota de 20/09/2026, a
    Zona Oeste tem 28% das quedas recentes, mas só 4,5% dos 200 CEPs do topo.

    Esta etapa testa, nas 8 datas de corte de J11, uma variante em que os pedidos na Light de
    cada CEP são multiplicados por (taxa da cidade / taxa da zona), com
    taxa = pedidos Pendentes por queda nos 12 meses anteriores ao corte (só o que se sabia na data).
    Compara com a nota atual em três coisas:
      1. acerto no topo (mesma medida de J12: árvore caída, risco/queda e novo pedido na Light);
      2. acerto só em árvore caída, que depende menos de como cada zona registra os pedidos;
      3. parte de cada zona no topo x parte de cada zona nas quedas do ano seguinte.

    Atenção: o alvo "novo pedido travado na Light" também é Pendente, então tem o mesmo viés.
    Uma nota corrigida pode perder acerto nesse alvo mesmo sendo mais justa entre as zonas.

Lê:
    pri_roll.pkl, P.pkl
Grava:
    vies_zona.json
Usado em:
    Ainda não usado no site; resultado para discutir com o grupo.
Escrito para este pacote (não fazia parte da análise original).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _comum import *   # caminhos das pastas e arquivos; passa a trabalhar na pasta trabalho/

import pandas as pd, numpy as np, pickle, json

O = pickle.load(open('pri_roll.pkl', 'rb'))
P = pd.read_pickle('P.pkl')
P = P[P.cep.notna() & P.zona.notna()].copy(); P['cep'] = P.cep.astype('int64')
zona_cep = P.groupby('cep').zona.agg(lambda s: s.mode().iloc[0])   # zona mais comum dos pedidos do CEP

L = lambda v, cap: np.clip(np.log1p(v) / np.log1p(cap), 0, 1)
PESOS = np.array([25, 15, 40, 10, 10], float)
KS = (200, 500, 1000)
Y = ['y_queda', 'y_rq', 'y_light']

def sinais(g, light):
    return np.stack([L(g.risco + g.queda12, 12), L(g.com, 8), L(light, 12),
                     np.clip((g.prob - 0.07) / 0.48, 0, 1), np.clip(g.esp / 365, 0, 1)], 1)

def acertos(score, Yv):
    o = np.argsort(-score, kind='stable')
    return np.array([[Yv[o[:k], j].mean() for k in KS] for j in range(Yv.shape[1])])   # alvo x K

res = {}
linhas = []
for T, g in O.items():
    g = g[g.active].copy()
    g['zona'] = zona_cep.reindex(g.index).values
    # taxa de Pendente por queda em cada zona, só com o que se sabia em T
    tz = g.groupby('zona')[['light', 'queda12']].sum()
    taxa = tz.light / tz.queda12.clip(lower=1)
    fator = (tz.light.sum() / max(tz.queda12.sum(), 1)) / taxa.replace(0, np.nan)
    f = g.zona.map(fator).fillna(1.0).values      # zona desconhecida ou sem Pendente: sem correção
    Yv = np.stack([(g[y].values > 0) for y in Y], 1)
    s_atual = sinais(g, g.light) @ PESOS
    s_corr = sinais(g, g.light * f) @ PESOS
    a_atual, a_corr = acertos(s_atual, Yv), acertos(s_corr, Yv)
    # parte de cada zona: no top 500 e nas quedas do ano seguinte
    top_at = pd.Series(g.zona.values[np.argsort(-s_atual, kind='stable')[:500]]).value_counts(normalize=True)
    top_co = pd.Series(g.zona.values[np.argsort(-s_corr, kind='stable')[:500]]).value_counts(normalize=True)
    quedas = g.groupby('zona').y_queda.sum(); quedas = quedas / quedas.sum()
    res[T] = dict(fator=fator.round(3).to_dict(),
                  acerto_atual=a_atual.round(4).tolist(), acerto_corrigida=a_corr.round(4).tolist(),
                  top500_atual=top_at.round(3).to_dict(), top500_corrigida=top_co.round(3).to_dict(),
                  quedas_ano_seguinte=quedas.round(3).to_dict())
    linhas.append(dict(corte=T, media_atual=a_atual.mean(), media_corrigida=a_corr.mean(),
                       queda_atual=a_atual[0].mean(), queda_corrigida=a_corr[0].mean(),
                       light_atual=a_atual[2].mean(), light_corrigida=a_corr[2].mean()))
    print(f'\n== corte {T}: fator por zona', {k: round(v, 2) for k, v in fator.items()})
    print(pd.DataFrame({'top500 atual': top_at, 'top500 corrigida': top_co, 'quedas ano seguinte': quedas})
          .fillna(0).mul(100).round(1).to_string())

R = pd.DataFrame(linhas).set_index('corte')
print('\nAcerto médio nos 200/500/1000 do topo (%), por corte:')
print((R * 100).round(1).to_string())
print('\nMédia dos 8 cortes (%):'); print((R.mean() * 100).round(1).to_string())
json.dump(res, open('vies_zona.json', 'w'), ensure_ascii=False, indent=1, default=str)
