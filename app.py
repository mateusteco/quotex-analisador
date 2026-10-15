
import streamlit as st

st.set_page_config(
    page_title="Analisador Quotex M5",
    page_icon="📊"
)

st.title("📊 Analisador Quotex M5")
st.caption("Versão inicial")

par = st.selectbox(
    "Selecione um par",
    ["AUD/USD (OTC)"]
)

if st.button("Analisar M5"):
    st.success("O painel está funcionando!")
    st.info("Próxima etapa: conectar a OTCharts.")

st.warning("Protótipo sem dados reais.")
