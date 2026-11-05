import json
import os
import time
from datetime import datetime, timezone
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import futures_engine as engine

st.set_page_config(page_title='Nexus • BTC Futures', page_icon='📈', layout='wide')
st.title('Nexus • BTC Futures')
st.caption('BTCUSDT perpétuo · H4 / H1 / M15 / M5 · consulta a cada 15 segundos · análise e simulação')
st.warning('Estratégia experimental. Taxa de acerto ainda não validada. Nenhuma ordem é enviada à Binance.')


def local_time(ms):
    return datetime.fromtimestamp(ms/1000, timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M:%S')


@st.fragment(run_every='15s')
def dashboard():
    try:
        data = json.loads((engine.DATA_DIR/'status.json').read_text())
    except (FileNotFoundError, ValueError):
        st.info('Aguardando o monitor. Inicie: python futures_worker.py')
        return
    age = int(time.time()*1000)-data['checked_at']
    live = data.get('live',True)
    if not live:
        st.error('REPLAY OFFLINE — captura histórica. Não representa o mercado atual.')
    elif age > 60_000 or age < -60_000:
        st.error('Monitor desconectado ou relógio incorreto. Sinais desativados nesta tela.')
        st.caption('Última atualização: '+local_time(data['checked_at']))
        return
    st.caption('Última atualização: '+local_time(data['checked_at'])+' · horário de Brasília')
    if not data['ok']:
        st.error('AGUARDAR — '+ '; '.join(data['blocks']))
        return
    st.subheader(data['action'])
    if data['action']!='AGUARDAR' and live and int(time.time()*1000)>data['expires_at']:
        st.error('Sinal expirado. Aguarde nova análise.')
    else:
        for reason in data['blocks']:
            st.write('• '+reason)
    m = data['market']
    a,b,c,d = st.columns(4)
    a.metric('Preço de compra / venda',f"{m['ask']:,.2f} / {m['bid']:,.2f}")
    b.metric('Funding / intervalo',f"{m['funding']*100:.4f}%")
    c.metric('Variação OI · 5 min',f"{m['oi_change_pct']:.3f}%")
    d.metric('Agressão compradora',f"{m['buy_share']*100:.1f}%")
    st.dataframe(pd.DataFrame(data['readings']).T.rename(columns={'trend':'Tendência','rsi':'RSI','volume_ratio':'Volume relativo'}),use_container_width=True)
    if data['action']!='AGUARDAR':
        p=data['plan']
        st.table(pd.DataFrame({'Nível':['Entrada de referência','Stop','Alvo 1 · referência, sem parcial automática','Alvo 2 · 2R'],'Preço':[p['entry'],p['stop'],p['target1'],p['target2']]}))
        st.caption('Validade: '+local_time(data['expires_at'])+' · Probabilidade de acerto: ainda não estimada.')
    rows=data.get('prices',[])
    if rows:
        frame=pd.DataFrame(rows,columns=['time','open','high','low','close','volume','end','quote_volume','count','taker_base','taker_quote','ignore'])
        fig=go.Figure(go.Candlestick(x=pd.to_datetime(frame['time'],unit='ms',utc=True),open=frame['open'],high=frame['high'],low=frame['low'],close=frame['close'],name='BTCUSDT · M5'))
        fig.update_layout(height=390,xaxis_rangeslider_visible=False,margin=dict(l=10,r=10,t=10,b=10),template='plotly_dark')
        st.plotly_chart(fig,use_container_width=True)
    st.subheader('Contexto macro e cobertura')
    macro=data['macro']
    st.caption(macro['coverage'])
    for source in macro.get('sources',[]):
        st.write(('✅ ' if source['ok'] else '⚠️ ')+source['source'])
    for h in macro.get('headlines',[])[:8]:
        st.write(f"{local_time(h['published'])} · {h['source']}: {h['title']}")
        st.link_button('Fonte oficial',h['url'])
    st.subheader('Acompanhamento em simulação')
    st.caption('Entrada simulada na abertura do próximo M5, cancelada se desvio >0,25 ATR. Alvo 2 integral, stop primeiro se ambos tocarem na mesma vela. Custo hipotético: 0,14% por ida e volta. Funding conciliado por liquidação real quando disponível. Sem alavancagem. Resultados não são execuções reais.')
    history=data.get('history',[])
    settled=[r for r in history if 'pnl_r' in r]
    if settled:
        values=[r['pnl_r'] for r in reversed(settled)]
        equity,peak,dd=0.,0.,0.
        for value in values:
            equity+=value; peak=max(peak,equity); dd=max(dd,peak-equity)
        x,y,z=st.columns(3)
        x.metric('Operações conciliadas',len(values))
        y.metric('Resultado líquido · R',f'{sum(values):.2f}')
        z.metric('Maior queda acumulada · R',f'{dd:.2f}')
        st.caption(f"Acerto observado: {100*sum(v>0 for v in values)/len(values):.1f}% · amostra prospectiva; sem significância comprovada. R = risco inicial de cada operação.")
    if data.get('funding_error'):
        st.warning(data['funding_error'])
    if history:
        table=pd.DataFrame([dict(Horário=local_time(r['created']),Estado=r['status'],Entrada=r['entry'],Saída=r['exit'],Resultado_R=r.get('pnl_r'),Antes_funding_R=r['pnl_r_before_funding'],Telegram=r['notified'],ID=r['id']) for r in history])
        st.dataframe(table,use_container_width=True,hide_index=True)
        st.download_button('Exportar histórico CSV',table.to_csv(index=False),'nexus_btc_simulacao.csv','text/csv')
    else:
        st.info('Nenhum sinal registrado. O monitor aguarda todos os filtros; não força entradas.')
    st.caption(data.get('notification','Telegram não configurado'))


dashboard()
st.divider()
st.subheader('Revisão da agenda macro · validade de 24 horas')
st.caption('O sistema bloqueia novos sinais até revisar a agenda. Consulte os calendários oficiais e registre eventos em horário de Brasília. Bloqueio: 30 minutos antes até 60 minutos depois. Os feeds registram divulgações; não substituem a agenda futura.')
st.link_button('Calendário FOMC','https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm')
st.link_button('Calendário BLS','https://www.bls.gov/schedule/')
# Optional deployment password avoids unauthenticated writes on a shared dashboard.
password=os.environ.get('DASHBOARD_ADMIN_PASSWORD','')
admin=st.text_input('Senha para revisar agenda',type='password') if password else ''
with st.form('calendar'):
    text=st.text_area('Um evento por linha: AAAA-MM-DD HH:MM | Nome',placeholder='2026-11-06 10:30 | Emprego EUA',help='Use datas conferidas nos calendários oficiais. Deixe vazio apenas se não houver eventos relevantes nas próximas 24 horas.')
    reviewed=st.checkbox('Conferi os eventos relevantes das próximas 24h, incluindo juros, inflação e emprego.')
    submit=st.form_submit_button('Salvar revisão da agenda')
    if submit:
        if password and admin!=password:
            st.error('Senha inválida.')
        elif not reviewed:
            st.error('Confirme a revisão dos calendários oficiais.')
        else:
            try:
                from zoneinfo import ZoneInfo
                events=[]
                for line in text.splitlines():
                    if not line.strip(): continue
                    when,name=line.split('|',1)
                    dt=datetime.strptime(when.strip(),'%Y-%m-%d %H:%M').replace(tzinfo=ZoneInfo('America/Sao_Paulo'))
                    events.append(dict(time=int(dt.timestamp()*1000),name=name.strip()))
                engine.write_json(engine.DATA_DIR/'events.json',dict(reviewed_at=int(time.time()*1000),events=events))
                st.success('Agenda salva. O monitor aplicará a revisão no próximo ciclo.')
            except ValueError:
                st.error('Formato inválido. Use AAAA-MM-DD HH:MM | Nome, uma linha por evento.')
