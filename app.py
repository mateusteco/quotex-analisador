import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Analisador Quotex M5", page_icon="📊")
st.title("📊 Analisador Quotex M5")
st.caption("Dados da OTCharts • Análise sob demanda")

BASE = "https://otcharts.com"
KEY = st.secrets["OTCHARTS_API_KEY"]
HEADERS = {"Authorization": f"Bearer {KEY}"}

def consultar(rota, parametros=None):
    resposta = requests.get(
        BASE + rota,
        headers=HEADERS,
        params=parametros,
        timeout=20
    )
    resposta.raise_for_status()
    return resposta.json()

try:
    dados = consultar("/v1/symbols", {"venue": "quotex"})
    simbolos = dados.get("symbols", [])
    pares = {
        item.get("name", item["symbol"]): item["symbol"]
        for item in simbolos
        if isinstance(item, dict) and item.get("symbol")
    }
    if not pares:
        st.warning("Nenhum par disponível na resposta da API.")
        st.stop()

    escolha = st.selectbox("Selecione um par", list(pares))
    simbolo = pares[escolha]

    if st.button("🔎 Analisar M5", type="primary"):
        dados_velas = consultar("/v1/candles", {
            "venue": "quotex",
            "symbol": simbolo,
            "tf": 300,
            "limit": 100
        })
        velas = dados_velas.get("candles", [])
        df = pd.DataFrame(velas)

        if df.empty:
            st.warning("Sem candles disponíveis para esse par.")
        elif not {"open", "high", "low", "close"}.issubset(df.columns):
            st.error("Formato de candles inesperado.")
            st.json(dados_velas)
        else:
            df = df.copy()
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["close"])
            if len(df) < 21:
                st.warning("Histórico insuficiente para análise.")
            else:
                df["mm9"] = df["close"].rolling(9).mean()
                df["mm21"] = df["close"].rolling(21).mean()
                ultimo = df.iloc[-1]
                st.metric("Último fechamento recebido", f"{ultimo['close']:.5f}")
                st.line_chart(df[["close", "mm9", "mm21"]])
                st.write("Média móvel 9:", round(ultimo["mm9"], 5))
                st.write("Média móvel 21:", round(ultimo["mm21"], 5))
                if ultimo["mm9"] > ultimo["mm21"]:
                    st.info("Tendência recente das médias: alta.")
                elif ultimo["mm9"] < ultimo["mm21"]:
                    st.info("Tendência recente das médias: baixa.")
                else:
                    st.info("Médias sem direção definida.")
                st.warning("Tendência não é sinal de entrada. Não operar apenas com esta leitura.")

except requests.HTTPError as erro:
    st.error(f"Erro da API: {erro.response.status_code}")
    st.code(erro.response.text[:800])
except Exception as erro:
    st.error(f"Erro: {erro}")
