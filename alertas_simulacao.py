"""Alertas Telegram para sinais teoricos M1; nenhuma ordem e enviada."""
import os
import requests

def formatar_alerta(leitura, simbolo="BRLUSD_otc"):
    direcao = leitura.get("sinal_teorico")
    if direcao not in ("CALL", "PUT"):
        return None
    inicio = leitura["inicio"]
    return (
        "TESTE — SIMULACAO | NEXUS OTC\n"
        f"Ativo: {simbolo}\n"
        f"Sinal teorico: {direcao}\n"
        f"Vela M1 fechada (inicio UTC, epoch): {inicio}\n"
        f"Preco de referencia: {leitura['preco']:.6f}\n"
        f"MM9: {leitura['mm9']:.6f} | MM21: {leitura['mm21']:.6f}\n"
        f"RSI14: {leitura['rsi14']:.2f}\n"
        "Nao e recomendacao nem ordem de compra. Resultado nao validado."
    )

def enviar_alerta(leitura, simbolo="BRLUSD_otc", *, sessao=None):
    mensagem = formatar_alerta(leitura, simbolo)
    if mensagem is None:
        return False
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    cliente = sessao if sessao is not None else requests
    resposta = cliente.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": mensagem},
        timeout=15,
    )
    resposta.raise_for_status()
    if not resposta.json().get("ok"):
        raise RuntimeError("Telegram nao confirmou o envio")
    return True
