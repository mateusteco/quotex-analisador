import streamlit as st
import requests
import pandas as pd
import numpy as np
import plotly.graph_objects as go

st.set_page_config(page_title='Analisador Quotex', page_icon='📊', layout='wide')
st.title('📊 Analisador Quotex')
st.caption('Análise sob demanda • Protótipo educacional')
BASE = 'https://otcharts.com'


def consultar(rota, parametros=None):
    chave = st.secrets.get('OTCHARTS_API_KEY', '')
    if not chave:
        raise ValueError('Configure OTCHARTS_API_KEY nos Secrets do Streamlit.')
    resposta = requests.get(BASE + rota, headers={'Authorization': f'Bearer {chave}'}, params=parametros, timeout=25)
    resposta.raise_for_status()
    return resposta.json()


@st.cache_data(ttl=600)
def listar_pares():
    dados = consultar('/v1/symbols', {'venue': 'quotex'})
    return {f"{item.get('name', item['symbol'])} ({item['symbol']})": item['symbol'] for item in dados.get('symbols', []) if isinstance(item, dict) and item.get('symbol')}


def preparar(velas):
    df = pd.DataFrame(velas)
    if df.empty:
        return df
    for coluna in ('open', 'high', 'low', 'close'):
        if coluna not in df.columns:
            raise ValueError('Resposta da API sem os campos OHLC completos.')
        df[coluna] = pd.to_numeric(df[coluna], errors='coerce')
    df = df.dropna(subset=['open', 'high', 'low', 'close']).copy()
    for coluna in ('time', 'timestamp', 'ts', 't'):
        if coluna in df.columns:
            df[coluna] = pd.to_numeric(df[coluna], errors='coerce')
            df = df.sort_values(coluna).drop_duplicates(subset=coluna, keep='last')
            break
    return df.reset_index(drop=True)


def indicadores(df):
    df = df.copy()
    df['mm9'] = df['close'].rolling(9).mean()
    df['mm21'] = df['close'].rolling(21).mean()
    delta = df['close'].diff()
    ganhos = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    perdas = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = ganhos / perdas.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))
    df.loc[(perdas == 0) & (ganhos > 0), 'rsi'] = 100
    df.loc[(perdas == 0) & (ganhos == 0), 'rsi'] = 50
    return df


def direcao(df):
    if len(df) < 25:
        return 'INDEFINIDA'
    u = df.iloc[-1]
    if pd.isna(u['rsi']):
        return 'INDEFINIDA'
    if u['mm9'] > u['mm21'] and u['close'] > u['mm9'] and 50 < u['rsi'] < 70:
        return 'ALTA'
    if u['mm9'] < u['mm21'] and u['close'] < u['mm9'] and 30 < u['rsi'] < 50:
        return 'BAIXA'
    return 'INDEFINIDA'


def agrupar(df, quantidade):
    grupos = np.arange(len(df)) // quantidade
    return df.groupby(grupos).agg(open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last')).reset_index(drop=True)


def demonstracao():
    rng = np.random.default_rng(42)
    precos = 1.08 + np.cumsum(rng.normal(0, 0.00022, 900))
    aberturas = np.r_[1.08, precos[:-1]]
    return pd.DataFrame({'open': aberturas, 'high': np.maximum(aberturas, precos) + 0.00007, 'low': np.minimum(aberturas, precos) - 0.00007, 'close': precos})


def grafico_candles(df):
    ultimos = df.tail(80).reset_index(drop=True)
    x = list(range(len(ultimos)))
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=x, open=ultimos['open'], high=ultimos['high'], low=ultimos['low'], close=ultimos['close'], name='Candles', increasing_line_color='#16a34a', decreasing_line_color='#dc2626'))
    fig.add_trace(go.Scatter(x=x, y=ultimos['mm9'], name='MM9', mode='lines', line=dict(color='#f59e0b', width=2)))
    fig.add_trace(go.Scatter(x=x, y=ultimos['mm21'], name='MM21', mode='lines', line=dict(color='#2563eb', width=2)))
    menor = float(ultimos['low'].min())
    maior = float(ultimos['high'].max())
    margem = max((maior - menor) * 0.08, 0.0001)
    fig.update_layout(height=460, margin=dict(l=8, r=8, t=25, b=15), xaxis_title='Últimos candles M5', yaxis_title='Preço', xaxis_rangeslider_visible=False, yaxis=dict(range=[menor - margem, maior + margem], tickformat='.5f'), legend=dict(orientation='h', y=1.12), dragmode='pan')
    st.plotly_chart(fig, use_container_width=True, config={'displaylogo': False, 'scrollZoom': False})


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
        escolha = st.selectbox('Selecione o par', list(pares))
        simbolo = pares[escolha]
    except requests.HTTPError as erro:
        st.error(f'OTCharts indisponível: HTTP {erro.response.status_code}')
        st.code(erro.response.text[:500])
        st.stop()
    except Exception as erro:
        st.error(str(erro))
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
            st.warning('Os candles recebidos podem incluir uma vela ainda aberta. A validação dos horários ainda está pendente.')

        if any(len(df) < 25 for df in quadros.values()):
            st.error('Histórico insuficiente para os três tempos gráficos.')
            st.stop()

        quadros = {nome: indicadores(df) for nome, df in quadros.items()}
        leituras = {nome: direcao(df) for nome, df in quadros.items()}
        st.subheader('Leitura por tempo gráfico')
        for nome in ('H1', 'M15', 'M5'):
            rsi = quadros[nome].iloc[-1]['rsi']
            st.write(f'**{nome}: {leituras[nome]}** · RSI: {rsi:.1f}')

        if leituras['H1'] == leituras['M15'] == leituras['M5'] and leituras['M5'] in ('ALTA', 'BAIXA'):
            st.info(f"Viés técnico: {leituras['M5']}. Não é sinal de entrada validado.")
        else:
            st.info('AGUARDAR — tempos gráficos sem confirmação conjunta.')

        st.subheader('Candles e médias móveis — M5')
        grafico_candles(quadros['M5'])
        ultimo = quadros['M5'].iloc[-1]
        col1, col2 = st.columns(2)
        col1.metric('Último fechamento', f"{ultimo['close']:.5f}")
        col2.metric('RSI 14 — M5', f"{ultimo['rsi']:.1f}")
        st.write(f"MM9: **{ultimo['mm9']:.5f}** · MM21: **{ultimo['mm21']:.5f}**")
        st.caption('Os filtros técnicos são experimentais. Não existe taxa de acerto comprovada.')
        if modo == 'Demonstração (simulada)':
            st.warning('SIMULAÇÃO: não utilizar estes resultados para operar.')
        else:
            st.warning('Antes de operar, é necessário validar fechamento dos candles, consistência dos dados e resultados históricos.')
    except requests.HTTPError as erro:
        st.error(f'Erro da API: HTTP {erro.response.status_code}')
        st.code(erro.response.text[:500])
    except Exception as erro:
        st.error(f'Erro: {erro}')

st.divider()
st.subheader('🧪 Laboratório de assertividade — M5')
st.caption('Backtest ilustrativo. Somente dados fictícios; não mede desempenho real da Quotex.')

payout = st.slider('Payout hipotético (%)', min_value=60, max_value=95, value=91, step=1)
valor = st.number_input('Valor hipotético por operação (R$)', min_value=1.0, max_value=10000.0, value=10.0, step=1.0)


def backtest_simulado(payout_pct, aposta):
    """Decisão no fechamento de M5; resultado no fechamento do M5 seguinte.
    H1/M15 somente de blocos completos, sem antecipar candles futuros.
    """
    base = demonstracao().reset_index(drop=True)
    m5 = indicadores(base)
    m15 = indicadores(agrupar(base, 3))
    h1 = indicadores(agrupar(base, 12))
    registros = []
    # i é o candle M5 já fechado no instante da decisão.
    # Um bloco de 3 termina em 2,5,8...; de 12 em 11,23,35...
    for i in range(300, len(base) - 1):
        j15 = (i + 1) // 3 - 1
        j1h = (i + 1) // 12 - 1
        if j15 < 24 or j1h < 24:
            continue
        d5 = direcao(m5.iloc[:i + 1])
        d15 = direcao(m15.iloc[:j15 + 1])
        d1h = direcao(h1.iloc[:j1h + 1])
        if d5 not in ('ALTA', 'BAIXA') or d5 != d15 or d5 != d1h:
            continue
        entrada = float(base.iloc[i]['close'])
        saida = float(base.iloc[i + 1]['close'])
        if entrada == saida:
            resultado = 'EMPATE'
            lucro = 0.0
        elif (saida > entrada) == (d5 == 'ALTA'):
            resultado = 'ACERTO'
            lucro = aposta * payout_pct / 100
        else:
            resultado = 'ERRO'
            lucro = -aposta
        registros.append({'Candle': i, 'Direção': 'CALL' if d5 == 'ALTA' else 'PUT',
                          'Entrada': entrada, 'Saída': saida,
                          'Resultado': resultado, 'Lucro (R$)': lucro})
    return pd.DataFrame(registros)


if st.button('📋 Executar backtest demonstrativo'):
    resultados = backtest_simulado(payout, valor)
    if resultados.empty:
        st.info('Nenhuma operação passou pelos filtros neste conjunto fictício. Isso também é um resultado válido.')
    else:
        validos = resultados[resultados['Resultado'] != 'EMPATE']
        n = len(validos)
        acertos = int((validos['Resultado'] == 'ACERTO').sum())
        erros = int((validos['Resultado'] == 'ERRO').sum())
        empates = len(resultados) - n
        taxa = 100 * acertos / n if n else 0.0
        lucro = resultados['Lucro (R$)'].sum()
        a, b, c = st.columns(3)
        a.metric('Operações válidas', n)
        b.metric('Acertos / Erros', f'{acertos} / {erros}')
        c.metric('Acerto simulado', f'{taxa:.1f}%' if n else 'N/D')
        st.metric('Saldo hipotético', f'R$ {lucro:.2f}')
        if empates:
            st.caption(f'{empates} empates excluídos da taxa de acerto (lucro zero).')
        st.dataframe(resultados, use_container_width=True, hide_index=True)
        st.download_button('⬇️ Exportar testes (CSV)',
                           resultados.to_csv(index=False).encode('utf-8'),
                           file_name='backtest_ficticio.csv', mime='text/csv')
    st.warning('Os dados foram gerados aleatoriamente. Este teste NÃO valida uma estratégia lucrativa e não deve orientar operações reais.')
