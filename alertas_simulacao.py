"""Mensagens de sinais M1 exclusivamente simulados; nenhuma ordem e enviada."""
import os
from datetime import datetime, timezone, timedelta
import requests

BRASILIA = timezone(timedelta(hours=-3))

def formatar_alerta(leitura, simbolo="BRLUSD_otc"):
    direcao = leitura.get("sinal_teorico")
    if direcao not in ("CALL", "PUT"):
        return None
    # A leitura se refere a uma vela JA FECHADA. Nao prometer entrada futura.
    fechamento = datetime.fromtimestamp(int(leitura["inicio"]) + 60, BRASILIA)
    seta = "🟢 ⬆️" if direcao == "CALL" else "🔴 ⬇️"
    return (
        "👑 NEXUS OTC | QUOTEX M1\n"
        "🧪 TESTE — SIMULAÇÃO\n\n"
        f"📊 Ativo: {simbolo.replace('_otc', ' OTC').replace('BRLUSD', 'BRL/USD')}\n"
        "🔥 Período: M1\n"
        f"⌚ Fechamento da vela analisada (Brasília): {fechamento:%H:%M:%S}\n"
        f"📍 Sinal teórico: {direcao} {seta}\n"
        "🎯 Entrada única — SEM MARTINGALE\n\n"
        f"💰 Preço de referência: {leitura['preco']:.6f}\n"
        f"📈 MM9: {leitura['mm9']:.6f} | MM21: {leitura['mm21']:.6f}\n"
        f"📉 RSI14: {leitura['rsi14']:.2f}\n\n"
        "⚠️ Alerta retrospectivo da vela fechada; não garante entrada no horário indicado. "
        "Não é ordem nem recomendação. Resultado não validado."
    )

def formatar_resultado(direcao, preco_entrada, preco_saida, *, simbolo="BRLUSD_otc"):
    """Formata resultado apenas com preços efetivamente observados; não calcula payout."""
    if direcao not in ("CALL", "PUT"):
        raise ValueError("Direção inválida")
    entrada, saida = float(preco_entrada), float(preco_saida)
    if entrada <= 0 or saida <= 0:
        raise ValueError("Preços devem ser positivos")
    resultado = "EMPATE ➖" if saida == entrada else (
        "WIN ✅" if (saida > entrada) == (direcao == "CALL") else "LOSS ❌"
    )
    return (
        "👑 NEXUS OTC | RESULTADO SIMULADO\n"
        f"📊 Ativo: {simbolo}\n"
        f"📍 Direção: {direcao}\n"
        f"💰 Referência inicial: {entrada:.6f}\n"
        f"💰 Referência final: {saida:.6f}\n"
        f"🏆 Resultado teórico: {resultado}\n"
        "🧪 SEM MARTINGALE | Nenhuma operação executada."
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
        raise RuntimeError("Telegram não confirmou o envio")
    return True

def enviar_resultado(registro, *, sessao=None):
    """Envia apenas resultados de candles efetivamente apurados."""
    mensagem = registro["mensagem"]
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
        raise RuntimeError("Telegram não confirmou o resultado")
    return True
