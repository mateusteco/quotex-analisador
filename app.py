
import streamlit as st
import requests
import pandas as pd
import numpy as np

st.set_page_config(
    page_title="Analisador Quotex",
    page_icon="📊"
)

st.title("📊 Analisador Quotex")
st.caption("Análise sob demanda • Protótipo para testes")

BASE = "https://otcharts.com"


def consultar(rota, parametros=None):
    chave = st.secrets.get("OTCHARTS_API_KEY", "")

    if not chave:
        raise ValueError(
            "Configure OTCHARTS_API_KEY nos Secrets do Streamlit."
        )

    resposta = requests.get(
        BASE + rota,
        headers={"Authorization": f"Bearer {chave}"},
        params=parametros,
        timeout=25
    )

    resposta.raise_for_status()
    return resposta.json()


@st.cache_data(ttl=600)
def listar_pares():
    dados = consultar(
        "/v1/symbols",
        {"venue": "quotex"}
    )

    return {
        f"{item.get('name', item['symbol'])} ({item['symbol']})": item["symbol"]
        for item in dados.get("symbols", [])
        if isinstance(item, dict) and item.get("symbol")
    }


def preparar(velas):
    df = pd.DataFrame(velas)

    for coluna in ("open", "high", "low", "close"):
        if coluna not in df.columns:
            raise ValueError("Resposta sem OHLC completo.")

        df[coluna] = pd.to_numeric(
            df[coluna],
            errors="coerce"
        )

    df = df.dropna(
        subset=["open", "high", "low", "close"]
    ).copy()

    for coluna in ("time", "timestamp", "ts", "t"):
        if coluna in df.columns:
            df[coluna] = pd.to_numeric(
                df[coluna],
                errors="coerce"
            )

            df = df.sort_values(coluna)
            df = df.drop_duplicates(
                subset=coluna,
                keep="last"
            )
            break

    return df.reset_index(drop=True)


def indicadores(df):
    df = df.copy()

    df["mm9"] = df["close"].rolling(9).mean()
    df["mm21"] = df["close"].rolling(21).mean()

    delta = df["close"].diff()

    ganhos = delta.clip(lower=0).ewm(
        alpha=1 / 14,
        adjust=False
    ).mean()

    perdas = (-delta.clip(upper=0)).ewm(
        alpha=1 / 14,
        adjust=False
    ).mean()

    rs = ganhos / perdas.replace(0, np.nan)

    df["rsi"] = 100 - (100 / (1 + rs))

    df.loc[
        (perdas == 0) & (ganhos > 0),
        "rsi"
    ] = 100

    df.loc[
        (perdas == 0) & (ganhos == 0),
        "rsi"
    ] = 50

    return df


def direcao(df):
    if len(df) < 25:
        return "INDEFINIDA"

    ultimo = df.iloc[-1]

    if pd.isna(ultimo["rsi"]):
        return "INDEFINIDA"

    if (
        ultimo["mm9"] > ultimo["mm21"]
        and ultimo["close"] > ultimo["mm9"]
        and 50 < ultimo["rsi"] < 70
    ):
        return "ALTA"

    if (
        ultimo["mm9"] < ultimo["mm21"]
        and ultimo["close"] < ultimo["mm9"]
        and 30 < ultimo["rsi"] < 50
    ):
        return "BAIXA"

    return "INDEFINIDA"


def agrupar(df, quantidade):
    grupos = np.arange(len(df)) // quantidade

    return df.groupby(grupos).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last")
    ).reset_index(drop=True)


def demonstracao():
    rng = np.random.default_rng(42)

    precos = 1.08 + np.cumsum(
        rng.normal(0, 0.00022, 900)
    )

    aberturas = np.r_[1.08, precos[:-1]]

    return pd.DataFrame({
        "open": aberturas,
        "high": np.maximum(aberturas, precos) + 0.00007,
        "low": np.minimum(aberturas, precos) - 0.00007,
        "close": precos
    })


modo = st.radio(
    "Fonte dos dados",
    [
        "Demonstração (simulada)",
        "OTCharts (API)"
    ]
)

if modo == "Demonstração (simulada)":
    st.warning(
        "DADOS FICTÍCIOS: não representam preços "
        "da Quotex e não servem para operar."
    )

    st.selectbox(
        "Par (apenas exemplo)",
        ["EUR/USD OTC — simulado"],
        disabled=True
    )

    simbolo = None

else:
    try:
        pares = listar_pares()

        if not pares:
            st.warning(
                "Nenhum par autorizado retornado pela API."
            )
            st.stop()

        escolha = st.selectbox(
            "Selecione o par",
            list(pares)
        )

        simbolo = pares[escolha]

    except requests.HTTPError as erro:
        st.error(
            f"OTCharts indisponível: HTTP "
            f"{erro.response.status_code}"
        )
        st.code(erro.response.text[:500])
        st.stop()

    except Exception as erro:
        st.error(str(erro))
        st.stop()


if st.button(
    "🔎 Analisar M5 + M15 + H1",
    type="primary"
):
    try:
        if modo == "Demonstração (simulada)":
            base = demonstracao()

            quadros = {
                "M5": base,
                "M15": agrupar(base, 3),
                "H1": agrupar(base, 12)
            }

        else:
            quadros = {}

            for nome, tf in [
                ("M5", 300),
                ("M15", 900),
                ("H1", 3600)
            ]:
                dados = consultar(
                    "/v1/candles",
                    {
                        "venue": "quotex",
                        "symbol": simbolo,
                        "tf": tf,
                        "limit": 120
                    }
                )

                quadros[nome] = preparar(
                    dados.get("candles", [])
                )

            st.warning(
                "A API pode incluir candles ainda abertos. "
                "Sem validação do fechamento, não utilize "
                "esta análise como sinal de entrada."
            )

        quadros = {
            nome: indicadores(df)
            for nome, df in quadros.items()
        }

        leituras = {
            nome: direcao(df)
            for nome, df in quadros.items()
        }

        st.subheader("Leitura por tempo gráfico")

        for nome in ("H1", "M15", "M5"):
            df = quadros[nome]

            rsi = (
                df.iloc[-1]["rsi"]
                if len(df)
                else np.nan
            )

            if pd.notna(rsi):
                st.write(
                    f"**{nome}: {leituras[nome]}** "
                    f"· RSI: {rsi:.1f}"
                )
            else:
                st.write(
                    f"**{nome}: INDEFINIDA**"
                )

        alinhadas = (
            leituras["H1"]
            == leituras["M15"]
            == leituras["M5"]
        )

        if alinhadas and leituras["M5"] in (
            "ALTA",
            "BAIXA"
        ):
            st.info(
                f"Viés técnico: {leituras['M5']}. "
                "Não é sinal validado de entrada."
            )
        else:
            st.info(
                "AGUARDAR — tempos gráficos "
                "sem confirmação conjunta."
            )

        st.subheader(
            "Preços e médias móveis — M5"
        )

        df = quadros["M5"].tail(100).copy()

        if len(df) >= 25:
            grafico = df[
                ["close", "mm9", "mm21"]
            ].reset_index(drop=True)

            st.line_chart(
                grafico,
                height=350
            )

            ultimo = df.iloc[-1]

            st.metric(
                "Último fechamento",
                f"{ultimo['close']:.5f}"
            )

            st.metric(
                "RSI 14 — M5",
                f"{ultimo['rsi']:.1f}"
            )

            st.write(
                "Média móvel 9:",
                round(ultimo["mm9"], 5)
            )

            st.write(
                "Média móvel 21:",
                round(ultimo["mm21"], 5)
            )

        else:
            st.warning(
                "Histórico insuficiente para exibir médias."
            )

        st.caption(
            "MM9, MM21 e RSI são filtros ilustrativos. "
            "A estratégia ainda não possui "
            "assertividade comprovada."
        )

        if modo == "Demonstração (simulada)":
            st.warning(
                "SIMULAÇÃO: não utilizar estes "
                "resultados para operar."
            )
        else:
            st.warning(
                "Ainda precisamos validar os horários, "
                "os candles fechados, a consistência "
                "dos dados e os resultados históricos."
            )

    except requests.HTTPError as erro:
        st.error(
            f"Erro da API: HTTP "
            f"{erro.response.status_code}"
        )

        st.code(
            erro.response.text[:500]
        )

    except Exception as erro:
        st.error(f"Erro: {erro}")
