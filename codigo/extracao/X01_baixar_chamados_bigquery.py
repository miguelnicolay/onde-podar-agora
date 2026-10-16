"""
Extração · X01 — Baixar os chamados de manejo arbóreo do BigQuery (Data.Rio)
Tipo: preparação (roda antes de A01, só quando for atualizar os dados)

O que faz:
    Consulta a tabela pública `datario.adm_central_atendimento_1746.chamado`, com o mesmo
    recorte usado no projeto (tipo "Manejo Arbóreo", abertos de 01/09/2022 até o fim dos dados),
    e grava os chamados brutos, sem CEP nem setor, em dados_entrada/chamados_brutos.parquet.
    O CEP, o setor censitário e a coordenada usada são acrescentados depois, em X02.

Precisa:
    - uma conta Google com acesso a um projeto do Google Cloud (o BigQuery cobra a consulta
      desse projeto; esta consulta lê poucas colunas e fica dentro da cota gratuita mensal);
    - pip install basedosdados pyarrow

Uso:
    python X01_baixar_chamados_bigquery.py SEU-PROJETO-GCP [AAAA-MM-DD]

    O segundo argumento é o último dia dos dados. Sem ele, usa o último dia completo
    disponível na tabela (o dia anterior ao último chamado registrado).
Grava:
    dados_entrada/chamados_brutos.parquet
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'etapas'))
from _comum import ENTRADA, INICIO_DADOS

import pandas as pd
import basedosdados as bd

if len(sys.argv) < 2:
    raise SystemExit('Uso: python X01_baixar_chamados_bigquery.py SEU-PROJETO-GCP [AAAA-MM-DD]')
PROJETO = sys.argv[1]
TABELA = '`datario.adm_central_atendimento_1746.chamado`'

# Colunas que as etapas A a J usam (as outras da tabela não são necessárias).
COLUNAS = [
    'id_chamado', 'id_origem_ocorrencia', 'data_inicio', 'data_fim',
    'id_bairro', 'id_territorialidade', 'id_logradouro', 'numero_logradouro',
    'id_unidade_organizacional', 'nome_unidade_organizacional',
    'categoria', 'tipo', 'id_subtipo', 'subtipo', 'status',
    'latitude', 'longitude', 'situacao', 'tipo_situacao', 'justificativa_status',
    'reclamacoes', 'data_particao',
]

if len(sys.argv) > 2:
    fim = pd.Timestamp(sys.argv[2])
else:
    ultimo = bd.read_sql(f"SELECT MAX(data_inicio) AS m FROM {TABELA} WHERE tipo = 'Manejo Arbóreo'",
                         billing_project_id=PROJETO).m.iloc[0]
    fim = pd.Timestamp(ultimo).normalize() - pd.Timedelta(days=1)   # o último dia costuma estar incompleto
    print('Último chamado na tabela:', ultimo, '→ fim dos dados:', fim.date())

consulta = f"""
SELECT {', '.join(COLUNAS)}
FROM {TABELA}
WHERE tipo = 'Manejo Arbóreo'
  AND data_particao >= '{INICIO_DADOS.date()}'          -- corta partições antigas (consulta mais barata)
  AND DATE(data_inicio) BETWEEN '{INICIO_DADOS.date()}' AND '{fim.date()}'
"""
print(consulta)
df = bd.read_sql(consulta, billing_project_id=PROJETO)

# Conferências
dup = df.id_chamado.duplicated().sum()
print('chamados:', len(df), '| id_chamado repetidos:', dup)
print('período:', pd.to_datetime(df.data_inicio).min(), 'a', pd.to_datetime(df.data_inicio).max())
print('com latitude/longitude:', df.latitude.notna().mean().round(3))
print(df.subtipo.value_counts().head(12).to_string())
if dup:
    # A tabela do Data.Rio pode ter versões repetidas do mesmo chamado; fica a mais recente.
    df = df.sort_values('data_particao').drop_duplicates('id_chamado', keep='last')
    print('depois de tirar repetidos:', len(df))

os.makedirs(ENTRADA, exist_ok=True)
saida = os.path.join(ENTRADA, 'chamados_brutos.parquet')
df.to_parquet(saida, index=False)
open(os.path.join(ENTRADA, 'chamados_brutos_fim.txt'), 'w').write(str(fim.date()))
print('Gravado:', saida, '| fim dos dados:', fim.date())
print(f'Próximo passo: python X02_cep_setor_coordenada.py, depois python ../rodar_tudo.py --fim-dados {fim.date()}')
