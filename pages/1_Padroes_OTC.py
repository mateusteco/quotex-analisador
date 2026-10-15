import os
import pandas as pd
import requests
import streamlit as st

st.title("Detector de padrões — USD/BRL OTC")
st.caption("Pesquisa exploratória de sequências M5; não gera sinais de entrada.")

try:
    key = st.secrets.get("OTCHARTS_API_KEY", os.getenv("OTCHARTS_API_KEY"))
except Exception:
    key = os.getenv("OTCHARTS_API_KEY")
if not key:
    st.error("Configure OTCHARTS_API_KEY nos Secrets do Streamlit.")
    st.stop()

@st.cache_data(ttl=120)
def candles(api_key):
    r = requests.get("https://otcharts.com/v1/candles",
        headers={"Authorization": f"Bearer {api_key}"},
        params={"venue":"quotex","symbol":"BRLUSD_otc","tf":300,"limit":120},
        timeout=30)
    r.raise_for_status()
    d = pd.DataFrame(r.json().get("candles", []))
    if d.empty or not {"open","high","low","close"}.issubset(d):
        raise ValueError("Resposta sem candles OHLC.")
    t = next((x for x in ("time","timestamp","ts","t") if x in d), None)
    if t is None:
        raise ValueError("Timestamps ausentes.")
    v = pd.to_numeric(d[t], errors="coerce")
    d["inicio"] = (pd.to_datetime(v,unit="ms" if v.abs().median()>1e11 else "s",utc=True)
                   if v.notna().all() else pd.to_datetime(d[t],utc=True))
    for c in ("open","high","low","close"):
        d[c] = pd.to_numeric(d[c],errors="coerce")
    d = d.dropna(subset=["inicio","open","high","low","close"]).copy()
    rounded = d.inicio.dt.round("300s")
    d = d[(d.inicio-rounded).abs()<=pd.Timedelta(seconds=2)].copy()
    d["inicio"] = d.inicio.dt.round("300s")
    duplicates = d[d.duplicated("inicio",keep=False)]
    for _,g in duplicates.groupby("inicio"):
        if len(g[["open","high","low","close"]].drop_duplicates())>1:
            raise ValueError("Candles duplicados conflitantes.")
    d = d.sort_values("inicio").drop_duplicates("inicio")
    d = d[(d.high>=d[["open","low","close"]].max(axis=1)) &
          (d.low<=d[["open","high","close"]].min(axis=1))]
    d = d[d.inicio+pd.Timedelta(minutes=5)<=pd.Timestamp.now(tz="UTC")-pd.Timedelta(seconds=5)]
    return d.reset_index(drop=True)

try:
    df = candles(key)
except Exception as e:
    st.error(f"Erro na consulta: {e}")
    st.stop()
if len(df)<12:
    st.warning("Histórico insuficiente.")
    st.stop()

n=st.select_slider("Candles por sequência",options=[2,3,4,5],value=3)
df["cor"] = ["A" if c>o else "B" if c<o else "D" for o,c in zip(df.open,df.close)]
rows=[]
for i in range(n-1,len(df)-1):
    window=df.iloc[i-n+1:i+2]
    if (window.inicio.diff().dropna()!=pd.Timedelta(minutes=5)).any():
        continue
    rows.append({"Padrão":"".join(df.cor.iloc[i-n+1:i+1]),"Seguinte":df.cor.iloc[i+1]})
data=pd.DataFrame(rows)
if data.empty:
    st.warning("Nenhuma sequência contínua encontrada.")
    st.stop()
summary=data.groupby("Padrão").agg(
    Ocorrências=("Seguinte","size"),
    Altas=("Seguinte",lambda x:(x=="A").sum()),
    Baixas=("Seguinte",lambda x:(x=="B").sum()),
    Dojis=("Seguinte",lambda x:(x=="D").sum())
).reset_index()
summary["Alta (%)"]=(summary.Altas/summary.Ocorrências*100).round(1)
summary["Baixa (%)"]=(summary.Baixas/summary.Ocorrências*100).round(1)
summary=summary.sort_values("Ocorrências",ascending=False)
a,b,c=st.columns(3)
a.metric("Candles fechados",len(df))
b.metric("Sequências",len(data))
c.metric("Padrões distintos",len(summary))
st.dataframe(summary,hide_index=True,use_container_width=True)
st.caption("A = alta, B = baixa, D = doji. BBA = baixa, baixa, alta.")
st.warning("Apenas análise descritiva de uma janela curta. "
    "Frequências históricas não são probabilidades validadas. "
    "Padrões sobrepostos e testes múltiplos podem gerar resultados ilusórios. "
    "Precisamos coletar histórico maior e testar em dados futuros antes de avaliar entradas.")
