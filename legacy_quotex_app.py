import streamlit as st
import requests
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timezone

st.set_page_config(page_title='Analisador Quotex', page_icon='📊', layout='wide')
st.title('📊 Analisador Quotex')
st.caption('Análise sob demanda • Protótipo educacional • Versão 6.4')
BASE = 'https://otcharts.com'
PERIODOS = {'M5': 300, 'M15': 900, 'H1': 3600}


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


def preparar(velas, segundos, agora_utc=None):
    """A API deve fornecer timestamps do INÍCIO de cada candle, em UTC."""
    df = pd.DataFrame(velas)
    if df.empty:
        raise ValueError('A API não retornou candles.')
    for coluna in ('open', 'high', 'low', 'close'):
        if coluna not in df.columns:
            raise ValueError('Resposta da API sem campos OHLC completos.')
        df[coluna] = pd.to_numeric(df[coluna], errors='coerce')
    coluna_tempo = next((c for c in ('time', 'timestamp', 'ts', 't') if c in df.columns), None)
    if coluna_tempo is None:
        raise ValueError('A API não retornou timestamps. Análise bloqueada.')
    bruto = df[coluna_tempo]
    numerico = pd.to_numeric(bruto, errors='coerce')
    if numerico.notna().all():
        unidade = 'ms' if numerico.abs().median() > 1e11 else 's'
        df['inicio_utc'] = pd.to_datetime(numerico, unit=unidade, utc=True, errors='coerce')
    else:
        df['inicio_utc'] = pd.to_datetime(bruto, utc=True, errors='coerce')
    if df['inicio_utc'].isna().any():
        raise ValueError('Timestamp inválido. Análise bloqueada.')
    if df[['open', 'high', 'low', 'close']].isna().any().any():
        raise ValueError('Valores OHLC inválidos. Análise bloqueada.')
    df = df.sort_values('inicio_utc').drop_duplicates('inicio_utc', keep='last').copy()
    # A OTCharts pode registrar a vela 1 segundo depois da fronteira UTC.
    # Corrigimos apenas deslocamentos muito pequenos (até 2 segundos),
    # mantendo um bloqueio para horários realmente incompatíveis.
    # Operações nativas com datetime, sem converter para inteiros Unix.
    # Pandas pode armazenar timestamps em microssegundos ou nanossegundos,
    # dependendo da versão; astype(int64) causava datas em 1970.
    original = df['inicio_utc'].copy()
    grade = original.dt.round(f'{segundos}s')
    diferencas = (original - grade).abs()
    tolerancia = pd.Timedelta(seconds=2)
    if (diferencas > tolerancia).any():
        st.error(f'Horários incompatíveis com candles de {segundos // 60} minutos. Análise bloqueada.')
        st.write('Campo de horário recebido:', coluna_tempo)
        st.write('Últimos horários recebidos:', original.tail(5).dt.strftime('%Y-%m-%d %H:%M:%S.%f UTC').tolist())
        st.write('Deslocamentos em segundos:', diferencas.tail(5).dt.total_seconds().tolist())
        raise ValueError('Deslocamento temporal maior que a tolerância de 2 segundos.')
    df['inicio_utc'] = grade
    if (df['inicio_utc'].dt.year < 2020).any():
        raise ValueError('Datas inesperadamente antigas após normalização. Análise bloqueada.')
    # Verifica duplicidades depois do ajuste temporal. Não descarta candles
    # com preços diferentes: isso poderia alterar os indicadores silenciosamente.
    duplicados = df[df['inicio_utc'].duplicated(keep=False)].copy()
    if not duplicados.empty:
        conflito = False
        for _, grupo in duplicados.groupby('inicio_utc'):
            # Comparação exata: não misturar preços distintos do mesmo período.
            if len(grupo[['open', 'high', 'low', 'close']].drop_duplicates()) > 1:
                conflito = True
                break
        if conflito:
            st.error('A API retornou candles com preços diferentes para o mesmo intervalo. Análise bloqueada.')
            st.caption('Diagnóstico de duplicidades (horários UTC e preços, sem dados de autenticação):')
            amostra = duplicados[['inicio_utc', 'open', 'high', 'low', 'close']].tail(12).copy()
            amostra['inicio_utc'] = amostra['inicio_utc'].dt.strftime('%Y-%m-%d %H:%M:%S UTC')
            st.dataframe(amostra, use_container_width=True, hide_index=True)
            raise ValueError(f'{len(duplicados)} registros envolvidos em duplicidades conflitantes. Não foram descartados.')
        st.caption(f'{len(duplicados)} registros com horários repetidos e OHLC idênticos; cópias exatas ignoradas.')
        df = df.drop_duplicates(subset='inicio_utc', keep='last').copy()
    deslocamento_max = float(diferencas.dt.total_seconds().max())
    if deslocamento_max > 0:
        st.caption(f'Horários da API ajustados à grade UTC (deslocamento máximo: {deslocamento_max:.3f} s).')
    if ((df['high'] < df[['open', 'close', 'low']].max(axis=1)) |
            (df['low'] > df[['open', 'close', 'high']].min(axis=1))).any():
        raise ValueError('OHLC inconsistente. Análise bloqueada.')
    df['fim_utc'] = df['inicio_utc'] + pd.to_timedelta(segundos, unit='s')
    agora = pd.Timestamp(agora_utc if agora_utc is not None else datetime.now(timezone.utc))
    df = df[df['fim_utc'] <= agora - pd.Timedelta(seconds=5)].copy()
    if df.empty:
        raise ValueError('Não há candles fechados disponíveis.')
    # Não analisar um histórico com intervalos ausentes no trecho usado pelos indicadores.
    if len(df) >= 25 and (df['inicio_utc'].tail(25).diff().dropna() != pd.Timedelta(seconds=segundos)).any():
        raise ValueError('Há lacunas entre os últimos 25 candles. Análise bloqueada.')
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
    return direcao_linha(df.iloc[-1])


def direcao_linha(linha):
    if pd.isna(linha['mm9']) or pd.isna(linha['mm21']) or pd.isna(linha['rsi']):
        return 'INDEFINIDA'
    if linha['mm9'] > linha['mm21'] and linha['close'] > linha['mm9'] and 50 < linha['rsi'] < 70:
        return 'ALTA'
    if linha['mm9'] < linha['mm21'] and linha['close'] < linha['mm9'] and 30 < linha['rsi'] < 50:
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
    menor, maior = float(ultimos['low'].min()), float(ultimos['high'].max())
    margem = max((maior - menor) * 0.08, 0.0001)
    fig.update_layout(height=460, margin=dict(l=8, r=8, t=25, b=15), xaxis_title='Últimos candles M5', yaxis_title='Preço', xaxis_rangeslider_visible=False, yaxis=dict(range=[menor - margem, maior + margem], tickformat='.5f'), legend=dict(orientation='h', y=1.12), dragmode='pan')
    st.plotly_chart(fig, use_container_width=True, config={'displaylogo': False, 'scrollZoom': False})


modo = st.radio('Fonte dos dados', ['Demonstração (simulada)', 'OTCharts (API)'], index=1)
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
            agora = datetime.now(timezone.utc)
            for nome, tf in PERIODOS.items():
                dados = consultar('/v1/candles', {'venue': 'quotex', 'symbol': simbolo, 'tf': tf, 'limit': 120})
                quadros[nome] = preparar(dados.get('candles', []), tf, agora)
            for nome, tf in PERIODOS.items():
                fim = quadros[nome]['fim_utc'].iloc[-1]
                atraso = (pd.Timestamp(agora) - fim).total_seconds()
                st.caption(f'{nome}: último fechamento {fim.strftime("%d/%m/%Y %H:%M:%S UTC")} · idade {atraso/60:.1f} min')
                if atraso < -10:
                    st.error(f'Dados {nome} apresentam fechamento no futuro. Análise bloqueada.')
                    st.stop()
                if atraso > tf + 120:
                    st.error(f'Dados {nome} atrasados. Análise bloqueada.')
                    st.stop()
            st.success('Verificação automática: últimos candles fechados, horários alinhados e dados recentes.')
            st.caption('A validação pressupõe que a OTCharts informa o início do candle em UTC; confirme essa convenção com o fornecedor.')

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
            st.warning('Ainda é necessário confirmar a convenção dos timestamps e validar a estratégia antes de qualquer operação real.')
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
    base = demonstracao().reset_index(drop=True)
    m5 = indicadores(base)
    m15 = indicadores(agrupar(base, 3))
    h1 = indicadores(agrupar(base, 12))
    registros = []
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
        entrada, saida = float(base.iloc[i]['close']), float(base.iloc[i + 1]['close'])
        if entrada == saida:
            resultado, lucro = 'EMPATE', 0.0
        elif (saida > entrada) == (d5 == 'ALTA'):
            resultado, lucro = 'ACERTO', aposta * payout_pct / 100
        else:
            resultado, lucro = 'ERRO', -aposta
        registros.append({'Candle': i, 'Direção': 'CALL' if d5 == 'ALTA' else 'PUT', 'Entrada': entrada, 'Saída': saida, 'Resultado': resultado, 'Lucro (R$)': lucro})
    return pd.DataFrame(registros)


if st.button('📋 Executar backtest demonstrativo'):
    resultados = backtest_simulado(payout, valor)
    if resultados.empty:
        st.info('Nenhuma operação passou pelos filtros neste conjunto fictício.')
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
        st.download_button('⬇️ Exportar testes (CSV)', resultados.to_csv(index=False).encode('utf-8'), file_name='backtest_ficticio.csv', mime='text/csv')
    st.warning('Dados aleatórios: este teste NÃO valida a estratégia.')

st.divider()
st.subheader('📁 Validação com histórico importado — M5')
st.caption('Envie um CSV M5 com colunas time, open, high, low, close. O horário deve representar o INÍCIO do candle em UTC. Não use dados de outra corretora para validar OTC da Quotex.')
exemplo = demonstracao().copy()
exemplo.insert(0, 'time', pd.date_range('2026-10-01 00:00:00', periods=len(exemplo), freq='5min', tz='UTC').strftime('%Y-%m-%dT%H:%M:%SZ'))
st.download_button('⬇️ Baixar CSV fictício para testar a importação', data=exemplo.to_csv(index=False).encode('utf-8'), file_name='exemplo_ficticio_m5.csv', mime='text/csv', help='Arquivo artificial, sem cotações reais.')
st.warning('O CSV de exemplo é 100% fictício. Use-o somente para testar a importação.')


def ler_csv_historico(arquivo):
    bruto = pd.read_csv(arquivo)
    bruto.columns = [str(c).strip().lower() for c in bruto.columns]
    if 'time' not in bruto.columns:
        for alternativa in ('timestamp', 'datetime', 'date'):
            if alternativa in bruto.columns:
                bruto = bruto.rename(columns={alternativa: 'time'})
                break
    if not {'time', 'open', 'high', 'low', 'close'}.issubset(bruto.columns):
        raise ValueError('O CSV precisa das colunas: time, open, high, low, close.')
    tempo_numerico = pd.to_numeric(bruto['time'], errors='coerce')
    if tempo_numerico.notna().all():
        unidade = 'ms' if tempo_numerico.median() > 1e11 else 's'
        bruto['time'] = pd.to_datetime(tempo_numerico, unit=unidade, utc=True, errors='coerce')
    else:
        bruto['time'] = pd.to_datetime(bruto['time'], utc=True, errors='coerce')
    for coluna in ('open', 'high', 'low', 'close'):
        bruto[coluna] = pd.to_numeric(bruto[coluna], errors='coerce')
    bruto = bruto.dropna(subset=['time', 'open', 'high', 'low', 'close'])
    bruto = bruto.sort_values('time').drop_duplicates('time', keep='last').reset_index(drop=True)
    if len(bruto) < 350:
        raise ValueError('Histórico curto: envie ao menos 350 candles M5 consecutivos.')
    if ((bruto['time'].dt.minute % 5 != 0) | (bruto['time'].dt.second != 0)).any():
        raise ValueError('Horários não alinhados ao início de candles M5 (00, 05, 10...).')
    if ((bruto['high'] < bruto[['open', 'close', 'low']].max(axis=1)) | (bruto['low'] > bruto[['open', 'close', 'high']].min(axis=1))).any():
        raise ValueError('Candles com high/low incompatíveis com OHLC.')
    return bruto


def montar_periodo(df, minutos):
    tabela = df.set_index('time').resample(f'{minutos}min', origin='epoch', label='left', closed='left').agg(open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last'), quantidade=('close', 'count'))
    tabela = tabela[tabela['quantidade'] == minutos // 5].dropna().copy()
    tabela['fechamento_utc'] = tabela.index + pd.Timedelta(minutes=minutos)
    return indicadores(tabela.reset_index())


def backtest_historico(df, payout_pct, aposta):
    m5 = indicadores(df.copy())
    m15 = montar_periodo(df, 15)
    h1 = montar_periodo(df, 60)
    if len(m15) < 25 or len(h1) < 25:
        raise ValueError('Histórico insuficiente de H1 e M15 completos.')
    m5['fim_m5'] = m5['time'] + pd.Timedelta(minutes=5)
    for nome, tabela in [('m15', m15), ('h1', h1)]:
        aux = pd.DataFrame({'momento': tabela['fechamento_utc'], nome: tabela.apply(direcao_linha, axis=1)})
        m5 = pd.merge_asof(m5.sort_values('fim_m5'), aux.sort_values('momento'), left_on='fim_m5', right_on='momento', direction='backward').drop(columns=['momento'])
    m5['m5'] = m5.apply(direcao_linha, axis=1)
    registros = []
    for i in range(1, len(m5) - 1):
        atual, proximo, anterior = m5.iloc[i], m5.iloc[i + 1], m5.iloc[i - 1]
        if (atual['time'] - anterior['time'] != pd.Timedelta(minutes=5) or proximo['time'] - atual['time'] != pd.Timedelta(minutes=5)):
            continue
        d = atual['m5']
        if d not in ('ALTA', 'BAIXA') or d != atual['m15'] or d != atual['h1']:
            continue
        entrada, saida = float(atual['close']), float(proximo['close'])
        if saida == entrada:
            resultado, lucro = 'EMPATE', 0.0
        elif (saida > entrada) == (d == 'ALTA'):
            resultado, lucro = 'ACERTO', aposta * payout_pct / 100
        else:
            resultado, lucro = 'ERRO', -aposta
        registros.append({'Momento UTC': atual['fim_m5'], 'Direção': 'CALL' if d == 'ALTA' else 'PUT', 'Entrada': entrada, 'Saída': saida, 'Resultado': resultado, 'Lucro (R$)': lucro})
    return pd.DataFrame(registros)


historico = st.file_uploader('Importar CSV de candles M5', type=['csv'], key='historico_m5')
st.caption('A importação não comprova que os preços correspondem à Quotex.')
if historico is not None:
    try:
        dados_historicos = ler_csv_historico(historico)
        st.write(f'Candles importados: **{len(dados_historicos)}**')
        st.write(f"Período UTC: {dados_historicos['time'].iloc[0]} até {dados_historicos['time'].iloc[-1]}")
        intervalos = dados_historicos['time'].diff().dropna()
        lacunas = intervalos[intervalos > pd.Timedelta(minutes=5)]
        st.write(f'Intervalos com lacunas: **{len(lacunas)}**')
        if len(lacunas):
            st.warning('Foram encontradas lacunas. Operações que atravessam lacunas serão ignoradas.')
        else:
            st.success('Horários consecutivos, com intervalos de 5 minutos.')
        st.info('Hipótese simplificada: decisão no fechamento do M5 e expiração no fechamento do M5 seguinte. Execução real pode ter latência e preços diferentes.')
        if st.button('🧪 Validar histórico importado'):
            resultado_real = backtest_historico(dados_historicos, payout, valor)
            if resultado_real.empty:
                st.warning('Nenhuma operação passou pelos filtros neste histórico.')
            else:
                corte = dados_historicos['time'].iloc[int(len(dados_historicos) * 0.7)]
                resultado_real['Amostra'] = np.where(resultado_real['Momento UTC'] < corte, 'Desenvolvimento (70%)', 'Validação (30%)')
                resumo = []
                for nome, parte in resultado_real.groupby('Amostra'):
                    validas = parte[parte['Resultado'] != 'EMPATE']
                    n = len(validas)
                    acertos = int((validas['Resultado'] == 'ACERTO').sum())
                    resumo.append({'Amostra': nome, 'Operações': n, 'Acertos': acertos, 'Assertividade (%)': round(100 * acertos / n, 2) if n else None, 'Saldo hipotético (R$)': round(parte['Lucro (R$)'].sum(), 2)})
                st.dataframe(pd.DataFrame(resumo), hide_index=True, use_container_width=True)
                st.dataframe(resultado_real.tail(30), hide_index=True, use_container_width=True)
                st.download_button('⬇️ Baixar backtest do CSV', resultado_real.to_csv(index=False).encode('utf-8'), file_name='backtest_historico.csv', mime='text/csv')
                st.warning('Resultados históricos não garantem desempenho futuro. Ainda é uma avaliação preliminar.')
    except Exception as erro:
        st.error(f'Não foi possível validar o arquivo: {erro}')
