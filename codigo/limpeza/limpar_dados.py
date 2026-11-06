"""
Limpeza dos dados publicados no repositório.

Lê os arquivos originais (que continuam intactos, porque o site usa eles) e grava versões limpas
em dados_limpos/, mais um registro de cada valor alterado. Cada regra está explicada em
dados_limpos/README.md.

Uso (da raiz do repositório):
    python codigo/limpeza/limpar_dados.py

Precisa só de pandas e numpy.
"""
import os, io, json, zipfile
import numpy as np
import pandas as pd

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DADOS = os.path.join(RAIZ, 'dados')
ENTRADA = os.path.join(RAIZ, 'codigo', 'dados_entrada')
SAIDA = os.path.join(RAIZ, 'dados_limpos')
os.makedirs(SAIDA, exist_ok=True)

# Retângulo do município do Rio (o mesmo usado nas etapas do pipeline)
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = -23.10, -22.73, -43.80, -43.09
registro = []   # uma linha por valor alterado nos rankings e no Open-Meteo


def dentro_do_rio(lat, lon):
    return lat.between(LAT_MIN, LAT_MAX) & lon.between(LON_MIN, LON_MAX)


def anota(arquivo, chave, coluna, antes, depois, regra):
    registro.append(dict(arquivo=arquivo, chave=chave, coluna=coluna,
                         valor_original=antes, valor_limpo=depois, regra=regra))


def dist_km(lat1, lon1, lat2, lon2):
    """Distância aproximada em km (suficiente para a escala da cidade)."""
    return np.hypot((lat1 - lat2) * 111.0, (lon1 - lon2) * 102.5)


# ---------------------------------------------------------------------------
# 1. Ranking por CEP
# ---------------------------------------------------------------------------
ARQ = 'ranking_ceps_poda.csv'
c = pd.read_csv(os.path.join(DADOS, ARQ))
c['coordenada_estimada'] = False
c['local_preenchido'] = False

# R1. Coordenada impossível: fora do município, ou sem bairro (não caiu em nenhum setor censitário)
#     e a mais de 5 km dos outros CEPs do mesmo prefixo de 5 dígitos. Nesses casos a coordenada
#     vira a mediana dos outros CEPs do prefixo (só se houver pelo menos 3).
c['_ok'] = dentro_do_rio(c.lat, c.lon)
c['_pref'] = c.cep.str[:5]
med = c[c._ok].groupby('_pref').agg(mlat=('lat', 'median'), mlon=('lon', 'median'), n=('cep', 'size'))
c = c.join(med, on='_pref')
c['_dpref'] = dist_km(c.lat, c.lon, c.mlat, c.mlon)
corrigir = ~c._ok | (c.bairro.isna() & (c._dpref > 5) & (c.n >= 3))
for i in c.index[corrigir]:
    if pd.notna(c.at[i, 'n']) and c.at[i, 'n'] >= 3:
        novo_lat, novo_lon = round(c.at[i, 'mlat'], 6), round(c.at[i, 'mlon'], 6)
        motivo = 'fora do município' if not c.at[i, '_ok'] else f'sem bairro e a {c.at[i, "_dpref"]:.1f} km do prefixo'
        regra = f'R1: coordenada {motivo}; mediana de {int(c.at[i, "n"])} CEPs {c.at[i, "_pref"]}-xxx'
    else:
        novo_lat, novo_lon = np.nan, np.nan
        regra = 'R1: coordenada fora do município; sem CEPs do mesmo prefixo para estimar'
    anota(ARQ, c.at[i, 'cep'], 'lat', c.at[i, 'lat'], novo_lat, regra)
    anota(ARQ, c.at[i, 'cep'], 'lon', c.at[i, 'lon'], novo_lon, regra)
    c.at[i, 'lat'], c.at[i, 'lon'] = novo_lat, novo_lon
    c.at[i, 'coordenada_estimada'] = True

# R13. CEP longe dos outros CEPs do mesmo prefixo (só marcação, nada é alterado).
#      Indica que o CEP atribuído ou a localização está errado; o arquivo não permite dizer qual.
c['dist_km_ao_prefixo'] = dist_km(c.lat, c.lon, c.mlat, c.mlon).round(2).where(c.n >= 3)
c['cep_suspeito'] = c.dist_km_ao_prefixo > 5

# R2. Sem bairro, região ou zona: bairro = o mais comum entre os 5 CEPs mais próximos que têm;
#     região e zona = as mais comuns desse bairro. Só se o CEP mais próximo estiver a até 2 km.
LOCAL = ['bairro', 'regiao_administrativa', 'zona']
base = c[c.zona.notna() & c.lat.notna()]
ra_bairro = base.groupby('bairro').regiao_administrativa.agg(lambda s: s.mode().iloc[0])
zona_do_bairro = base.groupby('bairro').zona.agg(lambda s: s.mode().iloc[0])
for i in c.index[c.zona.isna() & c.lat.notna()]:
    d = dist_km(c.at[i, 'lat'], c.at[i, 'lon'], base.lat.values, base.lon.values)
    if np.sort(d)[0] > 2:
        continue
    bairro = base.iloc[np.argsort(d)[:5]].bairro.mode().iloc[0]
    novos = {'bairro': bairro, 'regiao_administrativa': ra_bairro[bairro], 'zona': zona_do_bairro[bairro]}
    for col in LOCAL:
        if pd.isna(c.at[i, col]):
            anota(ARQ, c.at[i, 'cep'], col, None, novos[col],
                  f'R2: sem {col}; bairro mais comum entre os 5 CEPs mais próximos (o mais perto a {np.sort(d)[0]:.2f} km)')
            c.at[i, col] = novos[col]
    c.at[i, 'local_preenchido'] = True

# R3. Bairro que aparece em duas zonas: usa a zona da maioria dos CEPs do bairro.
zona_bairro = c.groupby('bairro').zona.agg(lambda s: s.mode().iloc[0])
for i in c.index[c.bairro.notna() & (c.zona != c.bairro.map(zona_bairro))]:
    novo = zona_bairro[c.at[i, 'bairro']]
    anota(ARQ, c.at[i, 'cep'], 'zona', c.at[i, 'zona'], novo, 'R3: zona diferente da dos outros CEPs do mesmo bairro')
    c.at[i, 'zona'] = novo

# R4. Nome de região administrativa com acento, quando todas as outras estão sem.
for i in c.index[c.regiao_administrativa.eq('COMPLEXO DO ALEMÃO')]:
    anota(ARQ, c.at[i, 'cep'], 'regiao_administrativa', 'COMPLEXO DO ALEMÃO', 'COMPLEXO DO ALEMAO',
          'R4: nomes de região sem acento, como os demais')
    c.at[i, 'regiao_administrativa'] = 'COMPLEXO DO ALEMAO'

c = c.drop(columns=['_ok', '_pref', 'mlat', 'mlon', 'n', '_dpref'])
c.to_csv(os.path.join(SAIDA, 'ranking_ceps_poda_limpo.csv'), index=False)

# ---------------------------------------------------------------------------
# 2. Ranking por área de 150 m
# ---------------------------------------------------------------------------
ARQ = 'ranking_areas_150m.csv'
a = pd.read_csv(os.path.join(DADOS, ARQ))
ci = c.set_index('cep')

# R5. Mesmos nomes de ação do ranking por CEP.
NOMES = {'COMLURB pode ir já': 'COMLURB pode ir', 'Precisa da Light': 'Depende da Light',
         'COMLURB + Light': 'COMLURB + agendar Light'}
for i in a.index[a.acao_sugerida.isin(list(NOMES))]:
    a.at[i, 'acao_sugerida'] = NOMES[a.at[i, 'acao_sugerida']]
for velho, novo in NOMES.items():
    anota(ARQ, '(todas)', 'acao_sugerida', velho, novo, 'R5: mesmo nome usado no ranking por CEP')

# R6. Bairro, zona e coordenada da área = os do CEP de maior nota, já limpo.
for i in a.index:
    cep = a.at[i, 'cep_de_maior_nota']
    for col, col_cep in (('bairro', 'bairro'), ('zona', 'zona')):
        if pd.isna(a.at[i, col]) and pd.notna(ci.at[cep, col_cep]):
            anota(ARQ, a.at[i, 'area_150m'], col, None, ci.at[cep, col_cep], 'R6: copiado do CEP de maior nota (limpo)')
            a.at[i, col] = ci.at[cep, col_cep]
    if ci.at[cep, 'coordenada_estimada'] and a.at[i, 'n_ceps'] == 1:
        for col in ('lat', 'lon'):
            anota(ARQ, a.at[i, 'area_150m'], col, a.at[i, col], ci.at[cep, col], 'R6: área de um só CEP com coordenada corrigida em R1')
            a.at[i, col] = ci.at[cep, col]
a.to_csv(os.path.join(SAIDA, 'ranking_areas_150m_limpo.csv'), index=False)

# ---------------------------------------------------------------------------
# 3. Clima diário da cidade (Open-Meteo)
# ---------------------------------------------------------------------------
ARQ = 'clima_diario_rio_openmeteo.csv'
m = pd.read_csv(os.path.join(ENTRADA, ARQ))
for i in m.index[m.chuva_hora_max > 24]:   # R7
    anota(ARQ, m.at[i, 'data'], 'chuva_hora_max', m.at[i, 'chuva_hora_max'], 24, 'R7: mais de 24 horas de chuva num dia')
    m.at[i, 'chuva_hora_max'] = 24
m.to_csv(os.path.join(SAIDA, 'clima_diario_rio_openmeteo_limpo.csv'), index=False)

# ---------------------------------------------------------------------------
# 4. Chuva por estação (pluviômetros) — uma tabela diária só, com marcações
# ---------------------------------------------------------------------------
z = zipfile.ZipFile(os.path.join(ENTRADA, 'clima_estacoes_rio.zip'))
ler = lambda nome: pd.read_csv(io.BytesIO(z.read(nome)), parse_dates=['data'] if nome.startswith('diario') else None)
COLS = {  # nome no arquivo -> nome limpo
    'acumulado_chuva_15_min__soma_dia': 'chuva_dia_mm', 'acumulado_chuva_15min__soma_dia': 'chuva_dia_mm',
    'acumulado_chuva_15_min__max': 'chuva_max_15min_mm', 'acumulado_chuva_15min__max': 'chuva_max_15min_mm',
    'acumulado_chuva_1_h__max': 'chuva_max_1h_mm', 'acumulado_chuva_1h__max': 'chuva_max_1h_mm'}

partes = []
# R8. Alerta Rio: tabela de 15 min até 02/06/2024 e tabela de 5 min a partir de 03/06/2024
#     (de 07/02 a 02/06/2024 as duas têm os mesmos dados; fica uma só).
#     A tabela "15 min" grava a cada 5 min desde 07/02/2024: 288 medições esperadas a partir daí.
t = ler('diario__clima_pluviometro__taxa_precipitacao_alertario.csv').rename(columns=COLS)
t = t[t.data <= '2024-06-02'].assign(rede='Alerta Rio', tabela_origem='taxa_precipitacao_alertario')
t['medicoes_esperadas'] = np.where(t.data >= '2024-02-07', 288, 96)
partes.append(t)
t = ler('diario__clima_pluviometro__taxa_precipitacao_alertario_5min.csv').rename(columns=COLS)
t = t[t.data >= '2024-06-03'].assign(rede='Alerta Rio', tabela_origem='taxa_precipitacao_alertario_5min', medicoes_esperadas=288)
partes.append(t)
# INEA: a cada 15 min.
t = ler('diario__clima_pluviometro__taxa_precipitacao_inea.csv').rename(columns=COLS)
partes.append(t.assign(rede='INEA', tabela_origem='taxa_precipitacao_inea', medicoes_esperadas=96))
# Cemaden: uma medição por hora e só o máximo em 1 h (sem total do dia).
t = ler('diario__clima_pluviometro__taxa_precipitacao_cemaden.csv').rename(columns=COLS)
partes.append(t.assign(rede='Cemaden', tabela_origem='taxa_precipitacao_cemaden', medicoes_esperadas=24))
# WebSirene: o ritmo muda (cerca de 64 medições por dia até 2023, 96 em 2024);
# medições esperadas = valor mais comum entre as estações em cada mês.
t = ler('diario__clima_pluviometro__taxa_precipitacao_websirene.csv').rename(columns=COLS)
t['_mes'] = t.data.dt.to_period('M')
t['medicoes_esperadas'] = t.groupby('_mes').n_registros.transform(lambda s: s.mode().iloc[0])
partes.append(t.drop(columns='_mes').assign(rede='WebSirene', tabela_origem='taxa_precipitacao_websirene'))

ch = pd.concat(partes, ignore_index=True)
for col in ('chuva_dia_mm', 'chuva_max_15min_mm', 'chuva_max_1h_mm'):
    if col not in ch:
        ch[col] = np.nan
ch['cobertura'] = (ch.n_registros / ch.medicoes_esperadas).round(3)
ch['dia_completo'] = ch.cobertura.between(0.9, 1.0)                     # R9

# R10. Valores suspeitos (ficam na tabela, marcados).
motivos = pd.Series('', index=ch.index)
def marca(cond, texto):
    global motivos
    motivos = motivos.where(~cond, motivos.where(motivos.eq(''), motivos + '; ') + texto)
marca(ch.chuva_dia_mm > 300, 'mais de 300 mm no dia')
marca(ch.chuva_max_1h_mm > 200, 'mais de 200 mm em 1 h')
marca(ch.chuva_max_15min_mm > 100, 'mais de 100 mm em 15 min')
marca(ch.rede.eq('WebSirene') & ch.chuva_max_15min_mm.eq(60.0), 'leitura travada em 60 mm')
ch['motivo_suspeito'] = motivos.replace('', None)
ch['valor_suspeito'] = ch.motivo_suspeito.notna()

# R11. Total do dia confiável: dia completo, sem suspeita, rede com total diário confiável.
#      WebSirene fica de fora: o total do dia dela é 40% a 70% do Alerta Rio nos mesmos dias,
#      e em cerca de 10% dos dias o máximo em 1 h passa do total do dia.
ch['usar_total_dia'] = ch.dia_completo & ~ch.valor_suspeito & ch.chuva_dia_mm.notna() & ch.rede.ne('WebSirene')

ordem = ['rede', 'id_estacao', 'data', 'chuva_dia_mm', 'chuva_max_15min_mm', 'chuva_max_1h_mm', 'n_registros',
         'medicoes_esperadas', 'cobertura', 'dia_completo', 'valor_suspeito', 'motivo_suspeito', 'usar_total_dia',
         'tabela_origem']
ch = ch[ordem].sort_values(['rede', 'id_estacao', 'data'])
ch['data'] = ch.data.dt.strftime('%Y-%m-%d')
ch.to_csv(os.path.join(SAIDA, 'chuva_estacoes_diaria_limpa.csv'), index=False)

# Cadastro único das estações
est = []
for rede, arq in (('Alerta Rio', 'alertario'), ('Cemaden', 'cemaden'), ('INEA', 'inea'), ('WebSirene', 'websirene')):
    e = ler(f'estacoes__clima_pluviometro__estacoes_{arq}.csv')
    est.append(e[['id_estacao', 'estacao', 'latitude', 'longitude']].assign(rede=rede))
est = pd.concat(est, ignore_index=True)
est['coordenada_valida'] = dentro_do_rio(est.latitude, est.longitude)      # R12
dias = ch.groupby(['rede', 'id_estacao']).agg(primeiro_dia=('data', 'min'), ultimo_dia=('data', 'max'),
                                              dias_com_dados=('data', 'size'), dias_total_confiavel=('usar_total_dia', 'sum'))
est = est.merge(dias.reset_index(), on=['rede', 'id_estacao'], how='left')
est['dias_com_dados'] = est.dias_com_dados.fillna(0).astype(int)
est['dias_total_confiavel'] = est.dias_total_confiavel.fillna(0).astype(int)
est[['rede', 'id_estacao', 'estacao', 'latitude', 'longitude', 'coordenada_valida', 'primeiro_dia', 'ultimo_dia',
     'dias_com_dados', 'dias_total_confiavel']].sort_values(['rede', 'id_estacao']) \
    .to_csv(os.path.join(SAIDA, 'estacoes_pluviometricas.csv'), index=False)

# ---------------------------------------------------------------------------
# 5. Registro e resumo
# ---------------------------------------------------------------------------
pd.DataFrame(registro).to_csv(os.path.join(SAIDA, 'registro_limpeza.csv'), index=False)
resumo = {
    'ranking_ceps': {'linhas': len(c), 'coordenada_estimada': int(c.coordenada_estimada.sum()),
                     'sem_coordenada': int(c.lat.isna().sum()), 'local_preenchido': int(c.local_preenchido.sum()),
                     'sem_zona_depois': int(c.zona.isna().sum()),
                     'cep_suspeito': int(c.cep_suspeito.sum()),
                     'cep_suspeito_no_top500': int(c[c.posicao <= 500].cep_suspeito.sum())},
    'ranking_areas': {'linhas': len(a), 'sem_zona_depois': int(a.zona.isna().sum())},
    'openmeteo': {'linhas': len(m)},
    'chuva_estacoes': {
        'linhas': len(ch),
        'por_rede': ch.groupby('rede').agg(linhas=('data', 'size'), dia_completo=('dia_completo', 'mean'),
                                           suspeitos=('valor_suspeito', 'sum'), usar_total_dia=('usar_total_dia', 'sum'))
                      .round(3).reset_index().to_dict('records'),
        'motivos': ch.motivo_suspeito.value_counts().to_dict()},
    'estacoes': {'linhas': len(est), 'coordenada_invalida': int((~est.coordenada_valida).sum())},
    'alteracoes_registradas': len(registro),
}
json.dump(resumo, open(os.path.join(SAIDA, 'resumo_limpeza.json'), 'w'), ensure_ascii=False, indent=1, default=int)
print(json.dumps(resumo, ensure_ascii=False, indent=1, default=int))
