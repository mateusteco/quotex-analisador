"""Contrato de ticks OTCharts; somente leitura de preços, nunca ordens."""
import json
from datetime import datetime
from math import isfinite

SYMBOL = "AUDUSD_otc"
STREAM_URL = "https://otcharts.com/v1/stream"


def timestamp_segundos(valor):
    if isinstance(valor, bool) or valor is None:
        raise ValueError("Timestamp inválido")
    try:
        ts = float(valor)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                raise ValueError("Timestamp sem fuso")
            ts = dt.timestamp()
        except (TypeError, ValueError, OverflowError):
            raise ValueError("Timestamp inválido") from None
    if not isfinite(ts) or ts < 0:
        raise ValueError("Timestamp inválido")
    if ts >= 1e11:
        ts /= 1000
    if ts >= 1e11:
        raise ValueError("Timestamp fora do intervalo em segundos/milissegundos")
    return ts


def normalizar_tick(dados, simbolo=SYMBOL):
    if not isinstance(dados, dict) or dados.get("symbol") != simbolo:
        return None
    try:
        if isinstance(dados.get("price"), bool):
            raise ValueError
        preco = float(dados["price"])
        ts = timestamp_segundos(dados["time"])
        if not isfinite(preco) or preco <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError("Tick OTCharts inválido") from None
    return ts, preco


def eventos_sse(linhas):
    """Respeita limites de eventos SSE, comentários e data multilinha."""
    evento, dados = "message", []
    for linha in linhas:
        if isinstance(linha, bytes):
            linha = linha.decode("utf-8")
        if not linha:
            if dados:
                try:
                    payload = json.loads("\n".join(dados))
                except ValueError:
                    raise ValueError("JSON SSE inválido") from None
                yield evento, payload
            evento, dados = "message", []
        elif linha.startswith("event:"):
            evento = linha[6:].strip()
        elif linha.startswith("data:"):
            dados.append(linha[5:].lstrip(" "))
