"""Mensagens M1 exclusivamente simuladas; nenhuma ordem é enviada."""
import os
from datetime import datetime, timezone, timedelta
from math import isfinite
import requests
from otcharts_stream import SYMBOL

BRASILIA = timezone(timedelta(hours=-3))


def horario(ts):
    return datetime.fromtimestamp(float(ts), BRASILIA).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] + ' UTC-03:00'


def formatar_alerta(leitura, simbolo=None):
    direcao = leitura.get("sinal_teorico")
    if direcao not in ("CALL", "PUT"):
        return None
    simbolo = simbolo or leitura.get("simbolo", SYMBOL)
    fechamento = int(leitura["inicio"]) + 60
    temporais = ""
    if "recebido_em" in leitura:
        temporais = (
            f"Recebido (Brasília): {horario(leitura['recebido_em'])}\n"
            f"Gerado (Brasília): {horario(leitura['gerado_em'])}\n"
            f"Latência do tick: {leitura['latencia_tick_ms']:.1f} ms\n"
            f"Atraso após fechamento: {leitura['latencia_fechamento_ms']:.1f} ms\n"
        )
    return (
        "👑 NEXUS OTC | QUOTEX M1\n"
        "🧪 TESTE — SIMULAÇÃO\n\n"
        f"📊 Ativo: {simbolo}\n"
        "🔥 Período: M1\n"
        f"⌚ Fechamento da vela analisada (Brasília): {horario(fechamento)}\n"
        f"{temporais}"
        f"📍 Sinal teórico: {direcao}\n"
        "SEM MARTINGALE\n\n"
        f"💰 Preço de referência: {leitura['preco']:.6f}\n"
        f"📈 MM9: {leitura['mm9']:.6f} | MM21: {leitura['mm21']:.6f}\n"
        f"📉 RSI14: {leitura['rsi14']:.2f}\n\n"
        "⚠️ Alerta retrospectivo da vela fechada. Não é entrada futura. "
        "Não é ordem nem recomendação. A próxima vela será avaliada apenas "
        "como referência estatística open/close; não representa execução."
    )


def formatar_resultado(direcao, preco_entrada, preco_saida, *, simbolo=SYMBOL, inicio=None):
    """Preços observados; não calcula payout nem representa preço executável."""
    if direcao not in ("CALL", "PUT"):
        raise ValueError("Direção inválida")
    entrada, saida = float(preco_entrada), float(preco_saida)
    if not all(isfinite(p) and p > 0 for p in (entrada, saida)):
        raise ValueError("Preços devem ser finitos e positivos")
    resultado = "EMPATE ➖" if saida == entrada else (
        "WIN ✅" if (saida > entrada) == (direcao == "CALL") else "LOSS ❌"
    )
    janela = "" if inicio is None else (
        f"Vela avaliada (Brasília): {horario(inicio)} até {horario(inicio + 60)}\n"
    )
    return (
        "👑 NEXUS OTC | RESULTADO SIMULADO\n"
        f"📊 Ativo: {simbolo}\n"
        f"📍 Direção: {direcao}\n"
        f"{janela}"
        f"💰 Referência inicial: {entrada:.6f}\n"
        f"💰 Referência final: {saida:.6f}\n"
        f"🏆 Resultado teórico: {resultado}\n"
        "Referências open/close dos ticks observados, sem payout ou execução.\n"
        "🧪 SEM MARTINGALE | Nenhuma operação executada."
    )


def _enviar(mensagem, sessao=None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Credenciais Telegram ausentes")
    cliente = sessao if sessao is not None else requests
    try:
        resposta = cliente.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": mensagem}, timeout=15,
        )
        resposta.raise_for_status()
        if not resposta.json().get("ok"):
            raise RuntimeError("Telegram não confirmou o envio")
    except (requests.RequestException, ValueError):
        # URLs de exceções requests podem conter o token. Nunca propagá-las.
        raise RuntimeError("Falha no envio Telegram; detalhes sensíveis omitidos") from None
    return True


def enviar_alerta(leitura, simbolo=None, *, sessao=None):
    mensagem = formatar_alerta(leitura, simbolo)
    return False if mensagem is None else _enviar(mensagem, sessao)


def enviar_resultado(registro, *, sessao=None):
    return _enviar(registro["mensagem"], sessao)
