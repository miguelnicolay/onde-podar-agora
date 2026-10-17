"""
Extração · X02 — Acrescentar coordenada usada, CEP e setor censitário aos chamados
Tipo: preparação (roda depois de X01 e antes de A01)

O que faz:
    Lê os chamados brutos de X01 e acrescenta as colunas que as etapas usam e que não vêm
    da tabela do 1746:

    latitude_usada, longitude_usada
        A coordenada do próprio chamado, quando cai dentro do retângulo do município.
        Sem coordenada válida, usa a mediana das coordenadas dos outros chamados do mesmo
        trecho (logradouro + faixa de 100 números), e depois a do mesmo logradouro.
    cep, cep_bairro_ref, cep_logradouro_ref, dist_km_ao_cep
        O CEP de referência mais próximo da coordenada usada, a distância até ele e o bairro e
        o logradouro desse CEP. A referência pode ser:
          (a) um CSV de CEPs com colunas cep, lat, lon, bairro, logradouro (--ceps ARQUIVO); ou
          (b) se não for dado, os próprios CSVs antigos dos chamados (os 4 "parteNde4.csv" em
              dados_entrada/), resumidos por CEP. Assim os CEPs ficam iguais aos já publicados,
              mas um CEP que nunca apareceu antes não é criado.
    cd_setor
        O setor censitário que contém a coordenada usada, pela malha de setores do IBGE
        (Censo 2022, estado do RJ: arquivo .shp, .gpkg ou .zip baixado do site do IBGE,
        passado em --setores ARQUIVO). A coluna do código na malha é CD_SETOR.

    ATENÇÃO: a regra exata usada para montar os CSVs originais não ficou registrada no
    repositório. As regras acima são uma reconstrução. Por isso, quando os CSVs antigos
    existem, esta etapa compara, nos chamados que aparecem nos dois, quantos ficaram com
    o mesmo CEP e o mesmo setor e a distância entre as coordenadas. Confira esse resultado
    antes de usar os dados novos no site.

Precisa:
    pip install geopandas pyarrow scikit-learn

Uso:
    python X02_cep_setor_coordenada.py --setores CAMINHO_DA_MALHA [--ceps ARQUIVO.csv] [--saida PASTA]

Lê:
    dados_entrada/chamados_brutos.parquet (de X01); a malha de setores; opcionalmente os CSVs antigos
Grava:
    PASTA/chamados_completo_com_cep_parte1de4.csv … parte4de4.csv (padrão: dados_entrada_atualizados/),
    e copia para lá o arquivo de setores e o clima, para rodar com
    python rodar_tudo.py --entrada dados_entrada_atualizados --fim-dados AAAA-MM-DD
"""
import os, sys, glob, re, shutil, argparse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'etapas'))
from _comum import ENTRADA, RAIZ, SETOR, CLIMA_OPENMETEO, CLIMA_ESTACOES_ZIP

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

# Retângulo do município (o mesmo das etapas E, F e J16)
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = -23.10, -22.73, -43.80, -43.09
R_TERRA_KM = 6371.0


def coordenada_usada(df):
    """Coordenada do chamado; sem ela, mediana do trecho; depois, mediana do logradouro."""
    lat = pd.to_numeric(df.latitude, errors='coerce')
    lon = pd.to_numeric(df.longitude, errors='coerce')
    ok = lat.between(LAT_MIN, LAT_MAX) & lon.between(LON_MIN, LON_MAX)
    df['latitude_usada'] = lat.where(ok)
    df['longitude_usada'] = lon.where(ok)
    df['origem_coordenada'] = np.where(ok, 'chamado', None)

    num = pd.to_numeric(df.numero_logradouro, errors='coerce')
    log = pd.to_numeric(df.id_logradouro, errors='coerce')
    trecho = log.astype('Int64').astype(str) + '_' + (num.where(num.between(1, 99999)) // 100).astype('Int64').astype(str)
    for chave, nome in ((trecho.where(log.notna() & num.between(1, 99999)), 'trecho'),
                        (log.astype('Int64').astype(str).where(log.notna()), 'logradouro')):
        base = pd.DataFrame({'k': chave, 'la': df.latitude_usada, 'lo': df.longitude_usada}).dropna()
        med = base.groupby('k')[['la', 'lo']].median()
        falta = df.latitude_usada.isna() & chave.notna()
        df.loc[falta, 'latitude_usada'] = chave[falta].map(med.la)
        df.loc[falta, 'longitude_usada'] = chave[falta].map(med.lo)
        preenchido = falta & df.latitude_usada.notna()
        df.loc[preenchido, 'origem_coordenada'] = nome
    print('origem da coordenada usada:'); print(df.origem_coordenada.value_counts(dropna=False).to_string())
    return df


def referencia_ceps(arquivo, antigos):
    if arquivo:
        ref = pd.read_csv(arquivo, dtype={'cep': str})
        ref = ref.rename(columns={'bairro': 'cep_bairro_ref', 'logradouro': 'cep_logradouro_ref'})
        print('CEPs de referência (arquivo):', len(ref))
    else:
        if antigos is None:
            raise SystemExit('Sem --ceps e sem os CSVs antigos dos chamados em dados_entrada/: não há referência de CEP.')
        a = antigos[antigos.cep.notna() & antigos.latitude_usada.notna()]
        moda = lambda s: s.mode().iloc[0] if s.notna().any() else None
        ref = a.groupby('cep').agg(lat=('latitude_usada', 'median'), lon=('longitude_usada', 'median'),
                                   cep_bairro_ref=('cep_bairro_ref', moda),
                                   cep_logradouro_ref=('cep_logradouro_ref', moda)).reset_index()
        print('CEPs de referência (resumo dos CSVs antigos):', len(ref))
    ref['cep'] = pd.to_numeric(ref.cep.astype(str).str.replace(r'\D', '', regex=True), errors='coerce')
    return ref.dropna(subset=['cep', 'lat', 'lon'])


def cep_mais_proximo(df, ref):
    ok = df.latitude_usada.notna()
    arvore = BallTree(np.radians(ref[['lat', 'lon']].values), metric='haversine')
    dist, idx = arvore.query(np.radians(df.loc[ok, ['latitude_usada', 'longitude_usada']].values), k=1)
    linha = ref.iloc[idx[:, 0]]
    df.loc[ok, 'cep'] = linha.cep.values
    df.loc[ok, 'cep_bairro_ref'] = linha.cep_bairro_ref.values
    df.loc[ok, 'cep_logradouro_ref'] = linha.cep_logradouro_ref.values
    df.loc[ok, 'dist_km_ao_cep'] = dist[:, 0] * R_TERRA_KM
    print('distância até o CEP (km): mediana', round(df.dist_km_ao_cep.median(), 3),
          '| 95%', round(df.dist_km_ao_cep.quantile(.95), 3))
    return df


def setor_censitario(df, arquivo_malha):
    import geopandas as gpd
    malha = gpd.read_file(arquivo_malha)
    col = next(c for c in malha.columns if c.upper() == 'CD_SETOR')
    malha = malha[[col, 'geometry']].to_crs(4674 if malha.crs is None else malha.crs)
    ok = df.latitude_usada.notna()
    pts = gpd.GeoDataFrame(df.loc[ok, ['id_chamado']],
                           geometry=gpd.points_from_xy(df.loc[ok, 'longitude_usada'], df.loc[ok, 'latitude_usada']),
                           crs=4674).to_crs(malha.crs)
    j = gpd.sjoin(pts, malha, how='left', predicate='within').drop_duplicates('id_chamado')
    codigo = j.set_index('id_chamado')[col].astype(str).str.replace(r'\D', '', regex=True)
    df['cd_setor'] = pd.to_numeric(df.id_chamado.map(codigo), errors='coerce').astype('Int64')
    print('com setor censitário:', round(df.cd_setor.notna().mean(), 3))
    return df


def ler_antigos():
    arqs = sorted(glob.glob(os.path.join(ENTRADA, '*chamados_completo_com_cep_parte*de4.csv')))
    if not arqs:
        return None
    return pd.concat([pd.read_csv(a, low_memory=False) for a in arqs], ignore_index=True)


def comparar(novo, antigo):
    if antigo is None:
        print('\nSem CSVs antigos para comparar.'); return
    m = novo.merge(antigo[['id_chamado', 'cep', 'cd_setor', 'latitude_usada', 'longitude_usada']],
                   on='id_chamado', suffixes=('', '_antigo'))
    print(f'\n== Comparação com os CSVs antigos ({len(m)} chamados em comum de {len(antigo)} antigos)')
    for c in ('cep', 'cd_setor'):
        a, b = pd.to_numeric(m[c], errors='coerce'), pd.to_numeric(m[c + '_antigo'], errors='coerce')
        tem = a.notna() & b.notna()
        print(f'{c}: igual em {(a[tem] == b[tem]).mean():.1%} dos que têm nos dois | '
              f'faltando no novo: {(a.isna() & b.notna()).sum()} | faltando no antigo: {(a.notna() & b.isna()).sum()}')
    d = np.hypot((m.latitude_usada - m.latitude_usada_antigo) * 111.0,
                 (m.longitude_usada - m.longitude_usada_antigo) * 102.5)
    print('distância entre a coordenada nova e a antiga (km): mediana', round(d.median(), 4),
          '| 95%', round(d.quantile(.95), 3), '| acima de 0,1 km:', f'{(d > .1).mean():.1%}')
    print('chamados antigos que não vieram na extração nova:', len(set(antigo.id_chamado) - set(novo.id_chamado)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--setores', required=True, help='malha de setores censitários do IBGE (RJ)')
    p.add_argument('--ceps', help='CSV de CEPs com colunas cep, lat, lon, bairro, logradouro')
    p.add_argument('--saida', default=os.path.join(RAIZ, 'dados_entrada_atualizados'))
    a = p.parse_args()

    df = pd.read_parquet(os.path.join(ENTRADA, 'chamados_brutos.parquet'))
    print('chamados brutos:', len(df))
    antigos = ler_antigos()
    df = coordenada_usada(df)
    df = cep_mais_proximo(df, referencia_ceps(a.ceps, antigos))
    df['cep'] = df.cep.astype('Int64')
    df = setor_censitario(df, a.setores)
    df = df.drop(columns=['origem_coordenada', 'data_particao'], errors='ignore')
    comparar(df, antigos)

    os.makedirs(a.saida, exist_ok=True)
    df = df.sort_values('data_inicio').reset_index(drop=True)
    for n, parte in enumerate(np.array_split(np.arange(len(df)), 4), start=1):
        df.iloc[parte].to_csv(os.path.join(a.saida, f'chamados_completo_com_cep_parte{n}de4.csv'), index=False)
    for f in (SETOR, CLIMA_OPENMETEO, CLIMA_ESTACOES_ZIP):
        if os.path.exists(f):
            shutil.copy2(f, a.saida)
    print('\nGravado em', a.saida)
    fim = open(os.path.join(ENTRADA, 'chamados_brutos_fim.txt')).read().strip() \
        if os.path.exists(os.path.join(ENTRADA, 'chamados_brutos_fim.txt')) else 'AAAA-MM-DD'
    print(f'Próximo passo: python rodar_tudo.py --entrada {a.saida} --fim-dados {fim}')
    print('Lembre de atualizar também o clima (Open-Meteo e pluviômetros) até essa data.')


if __name__ == '__main__':
    main()
