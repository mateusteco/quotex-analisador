import streamlit as st
import requests
import pandas as pd
import numpy as np

st.set_page_config(page_title='Analisador Quotex', page_icon='📊')
st.title('📊 Analisador Quotex')
st.caption('Análise sob demanda • Protótipo para testes')
BASE = 'https://otcharts.com'


def consultar(rota, parametros=None):
    chave = st.secrets.get('OTCHARTS_API_KEY', '')
    if not chave:
        raise ValueError('Configure OTCHARTS_API_KEY nos Secrets do Streamlit.')
    r = requests.get(BASE + rota, headers={'Authorization': f'Bearer {chave}'}, params=parametros, timeout=25)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=600)
def listar_pares():
    dados = consultar('/v1/symbols', {'venue': 'quotex'})
    return {f"{s.get('name', s['symbol'])} ({s['symbol']})": s['symbol'] for s in dados.get('symbols', []) if isinstance(s, dict) and s.get('symbol')}


def preparar(velas):
    df = pd.DataFrame(velas)
    for c in ('open', 'high', 'low', 'close'):
        if c not in df.columns:
            raise ValueError('Resposta sem OHLC completo.')
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=['open', 'high', 'low', 'close']).copy()
    for c in ('time', 'timestamp', 'ts', 't'):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
            df = df.sort_values(c).drop_duplicates(subset=c, keep='last')
            break
    return df.reset_index(drop=True)


def indicadores(df):
    df = df.copy()
    df['mm9'] = df.close.rolling(9).mean()
    df['mm21'] = df.close.rolling(21).mean()
    delta = df.close.diff()
    ganhos = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    perdas = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = ganhos / perdas.replace(0, np.nan)
    df['rsi'] = 100 - 100 / (1 + rs)
    df.loc[(perdas == 0) & (ganhos > 0), 'rsi'] = 100
    df.loc[(perdas == 0) & (ganhos == 0), 'rsi'] = 50
    return df


def direcao(df):
    if len(df) < 25:
        return 'INDEFINIDA'
    u = df.iloc[-1]
    if pd.isna(u['rsi']):
        return 'INDEFINIDA'
    if u.mm9 > u.mm21 and u.close > u.mm9 and 50 < u.rsi < 70:
        return 'ALTA'
    if u.mm9 < u.mm21 and u.close < u.mm9 and 30 < u.rsi < 50:
        return 'BAIXA'
    return 'INDEFINIDA'


def agrupar(df, n):
    grupos = np.arange(len(df)) // n
    return df.groupby(grupos).agg(open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last')).reset_index(drop=True)


def demonstracao():
    rng = np.random.default_rng(42)
    precos = 1.08 + np.cumsum(rng.normal(0, 0.00022, 900))
    aberturas = np.r_[1.08, precos[:-1]]
    return pd.DataFrame({'open': aberturas, 'high': np.maximum(aberturas, precos) + 0.00007,
                         'low': np.minimum(aberturas, precos) - 0.00007, 'close': precos})


modo = st.radio('Fonte dos dados', ['Demonstração (simulada)', 'OTCharts (API)'])
if modo == 'Demonstração (simulada)':
    st.warning('DADOS FICTÍCIOS: não representam preços da Quotex e não servem para operar.')
    st.selectbox('Par (apenas exemplo)', ['EUR/USD OTC — simulado'], disabled=True)
    simbolo = None
else:
    try:
        pares = listar_pares()
        if not pares:
            st.warning('Nenhum par autorizado retornado pela API.')
            st.stop()
        simbolo = pares[st.selectbox('Selecione o par', list(pares))]
    except requests.HTTPError as e:
        st.error(f'OTCharts indisponível: HTTP {e.response.status_code}')
        st.code(e.response.text[:500])
        st.stop()
    except Exception as e:
        st.error(str(e))
        st.stop()

if st.button('🔎 Analisar M5 + M15 + H1', type='primary'):
    try:
        if modo == 'Demonstração (simulada)':
            base = demonstracao()
            quadros = {'M5': base, 'M15': agrupar(base, 3), 'H1': agrupar(base, 12)}
        else:
            quadros = {}
            for nome, tf in [('M5', 300), ('M15', 900), ('H1', 3600)]:
                dados = consultar('/v1/candles', {'venue': 'quotex', 'symbol': simbolo, 'tf': tf, 'limit': 120})
                quadros[nome] = preparar(dados.get('candles', []))
            st.warning('A API pode incluir candle ainda aberto. Sem validação de fechamento, não use como sinal de entrada.')

        quadros = {nome: indicadores(df) for nome, df in quadros.items()}
        leituras = {nome: direcao(df) for nome, df in quadros.items()}
        st.subheader('Leitura por tempo gráfico')
        for nome in ('H1', 'M15', 'M5'):
            df = quadros[nome]
            rsi = df.iloc[-1]['rsi'] if len(df) else np.nan
            st.write(f"**{nome}: {leituras[nome]}** · RSI: {rsi:.1f}" if pd.notna(rsi) else f'**{nome}: INDEFINIDA**')

        alinhadas = leituras['H1'] == leituras['M15'] == leituras['M5']
        if alinhadas and leituras['M5'] in ('ALTA', 'BAIXA'):
            st.info(f"Viés técnico: {leituras['M5']}. Não é sinal validado de entrada.")
        else:
            st.info('AGUARDAR — tempos gráficos sem confirmação conjunta.')

        df = quadros['M5'].tail(100).copy()
        st.subheader('Preços e médias móveis — M5')
        if len(df) >= 25:
            graf = df[['close', 'mm9', 'mm21']].reset_index(drop=True)
            minimo = float(graf.min().min())
            maximo = float(graf.max().max())
            margem = max((maximo - minimo) * 0.1, 0.00001)
            st.line_chart(graf, y_min=minimo - margem, y_max=maximo + margem, height=300)
            st.metric('Último fechamento', f"{df.iloc[-1]['close']:.5f}")
        else:
            st.warning('Histórico insuficiente para exibir médias.')
        st.caption('MM9, MM21 e RSI são filtros ilustrativos, não uma estratégia com assertividade comprovada.')
        if modo == 'Demonstração (simulada)':
            st.warning('SIMULAÇÃO: não usar estes resultados para operar.')
        else:
            st.warning('Ainda falta validar horários, candles fechados, consistência entre tempos gráficos e resultados históricos.')
    except requests.HTTPError as e:
        st.error(f'Erro da API: HTTP {e.response.status_code}')
        st.code(e.response.text[:500])
    except Exception as e:
        st.error(f'Erro: {e}')
