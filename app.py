"""Explicit navigation keeps legacy Quotex pages out of the Futures dashboard."""
import streamlit as st
st.navigation([st.Page('futures_app.py', title='BTC Futures', default=True)]).run()
