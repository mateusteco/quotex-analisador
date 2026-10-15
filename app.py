import streamlit as st
import requests
import pandas as pd
import numpy as np

st.set_page_config(page_title='Analisador Quotex', page_icon='📊')
st.title('📊 Analisador Quotex')
st.caption('Protótipo educacional • Sem sinais de lucro garantido')

BASE = 'https://otcharts.com'


def consultar(rota, parametros=None):
    chave = st.secrets.get('OTCHARTS_API_KEY', '')
    if not chave:
        raise ValueError('Configure OTCHARTS_API_KEY nos Secrets do Streamlit.')
    resposta = requests.get(BASE + rota, headers={'Authorization': f'Bearer {chave}'}, params=parametros, timeout=20)
    resposta.raise_for_status()
    return resposta.json()


@st.cache_data(ttl=600)
def listar_pares():
    dados = consultar('/v1/symbols', {'venue': 'quotex'})
    return {f"{item.get('name', item['symbol'])} ({item['symbol']})": item['symbol'] for item in dados.get('symbols', []) if isinstance(item, dict) and item.get('symbol')}


def preparar(velas):
    df = pd.DataFrame(velas).copy()
    for campo in ('open', 'high', 'low', 'close'):
        if campo not in df:
            raise ValueError(f'Campo ausente nos candles: {campo}')
        df[campo] = pd.to_numeric(df[campo], errors='coerce')
    df = df.dropna(subset=['open', 'high', 'low', 'close'])
    for campo in ('time', 'timestamp', 'ts', 't'):
        if campo in df.columns:
            df = df.sort_values(campo).drop_duplicates(subset=[campo], keep='last')
            break
    return df.reset_index(drop=True)


def analisar(df):
    df = df.copy()
    df['mm9'] = df['close'].rolling(9).mean()
    df['mm21'] = df['close'].rolling(21).mean()
    variacao = df['close'].diff()
    ganho = variacao.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    perda = (-variacao.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = ganho / perda.replace(0, np.nan)
    df['rsi14'] = 100 - 100 / (1 + rs)
    ultimo = df.iloc[-1]
    anterior = df.iloc[-2]
    alta = ultimo['mm9'] > ultimo['mm21'] and ultimo['close'] > ultimo['mm9'] and 50 < ultimo['rsi14'] < 70
    baixa = ultimo['mm9'] < ultimo['mm21'] and ultimo['close'] < ultimo['mm9'] and 30 < ultimo['rsi14'] < 50
    if alta and ultimo['close'] > anterior['close']:
        leitura = 'Viés de alta — NÃO é recomendação de entrada'
    elif baixa and ultimo['close'] < anterior['close']:
        leitura = 'Viés de baixa — NÃO é recomendação de entrada'
    else:
        leitura = 'AGUARDAR — condições não alinhadas'
    return df, leitura


modo = st.radio('Fonte dos dados', ['Demonstração (simulada)', 'OTCharts (API)'])
if modo == 'Demonstração (simulada)':
    st.warning('DADOS FICTÍCIOS. Não correspondem à Quotex nem devem ser usados para operar.')
    par = 'EUR/USD OTC — exemplo fictício'
else:
    try:
        pares = listar_pares()
        if not pares:
            st.warning('A API não retornou pares disponíveis.')
            st.stop()
        nome = st.selectbox('Selecione o par', list(pares))
        par = pares[nome]
    except requests.HTTPError as erro:
        st.error(f'API indisponível (HTTP {erro.response.status_code}).')
        st.code(erro.response.text[:500])
        st.stop()
    except Exception as erro:
        st.error(str(erro))
        st.stop()

st.write('Tempo gráfico: **M5 (5 minutos)**')
if st.button('🔎 Analisar M5', type='primary'):
    try:
        if modo == 'Demonstração (simulada)':
            rng = np.random.default_rng(42)
            precos = 1.08 + np.cumsum(rng.normal(0, 0.00025, 120))
            aberturas = np.r_[precos[0], precos[:-1]]
            velas = [{'open': float(a), 'high': float(max(a, c) + 0.0001), 'low': float(min(a, c) - 0.0001), 'close': float(c)} for a, c in zip(aberturas, precos)]
        else:
            resposta = consultar('/v1/candles', {'venue': 'quotex', 'symbol': par, 'tf': 300, 'limit': 150})
            velas = resposta.get('candles', [])
        df = preparar(velas)
        if len(df) < 30:
            st.warning('Histórico insuficiente para calcular os indicadores.')
            st.stop()
        df, leitura = analisar(df)
        ultimo = df.iloc[-1]
        st.metric('Último fechamento recebido', f"{ultimo['close']:.5f}")
        st.metric('RSI 14', f"{ultimo['rsi14']:.1f}" if pd.notna(ultimo['rsi14']) else 'Indisponível')
        st.line_chart(df[['close', 'mm9', 'mm21']])
        st.info(leitura)
        if modo == 'OTCharts (API)':
            st.warning('Análise preliminar: ainda não valida candles fechados, alinhamento M15/H1 nem desempenho histórico. Não operar com base neste resultado.')
        else:
            st.warning('Resultado ilustrativo gerado com dados fictícios.')
    except requests.HTTPError as erro:
        st.error(f'Erro da API: {erro.response.status_code}')
        st.code(erro.response.text[:500])
    except Exception as erro:
        st.error(f'Erro: {erro}')
