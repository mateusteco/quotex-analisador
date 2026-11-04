"""Validação ao vivo OTCharts -> M1 -> Telegram opcional, sem ordens."""
import json
import os
import time
import requests
from fluxo_alertas_m1 import FluxoM1
from otcharts_stream import SYMBOL, STREAM_URL, eventos_sse, normalizar_tick


def executar(*, cliente=requests, duracao=1800, relogio=time.time, monotonic=time.monotonic, exigir_m1=True):
    key = os.getenv("OTCHARTS_API_KEY")
    if not key:
        raise RuntimeError("OTCHARTS_API_KEY não configurada")
    telegram = exigir_m1 and os.getenv('ENVIAR_TELEGRAM_SIMULACAO') == '1'
    fluxo = FluxoM1(enviar_telegram=telegram, sessao=cliente, relogio=relogio)
    inicio = monotonic()
    fechados = leituras = invalidos = 0
    conectado = False
    try:
        with cliente.get(
            STREAM_URL,
            headers={"Authorization": f"Bearer {key}", "Accept": "text/event-stream"},
            params={"venue": "quotex", "symbol": SYMBOL},
            stream=True, timeout=(10, 20)
        ) as response:
            response.raise_for_status()
            for evento, dados in eventos_sse(response.iter_lines(chunk_size=1, decode_unicode=True)):
                recebido = relogio()
                if monotonic() - inicio > duracao:
                    break
                if evento in ('dropped', 'closed', 'replaced'):
                    raise RuntimeError("Stream interrompido pela OTCharts; validação incompleta")
                if evento == 'connected':
                    conectado = True
                    continue
                if evento not in ('tick', 'message'):
                    continue
                try:
                    tick = normalizar_tick(dados)
                    if tick is None:
                        continue
                    antes = fluxo.builder.atual.inicio if fluxo.builder.atual else None
                    mensagem = fluxo.tick(*tick, recebido_em=recebido)
                except ValueError:
                    invalidos += 1
                    continue
                depois = fluxo.builder.atual.inicio if fluxo.builder.atual else None
                if antes is not None and depois > antes:
                    fechados += 1
                    if fluxo.ultima_leitura and fluxo.ultima_leitura['inicio'] == antes:
                        leituras += 1
                if mensagem:
                    print(mensagem)
                if telegram:
                    if fluxo.apurador.resultados and fechados >= 22 and fluxo.apurador.pendente is None:
                        break
                elif (exigir_m1 and fechados >= 22 and leituras >= 1) or (not exigir_m1 and fluxo.metricas["ticks_aceitos"] >= 10):
                    break
    except requests.RequestException:
        raise RuntimeError("Falha HTTP/stream OTCharts; detalhes sensíveis omitidos") from None
    relatorio = dict(simbolo=SYMBOL, conectado=conectado, candles_fechados=fechados,
                     leituras=leituras, ticks_invalidos=invalidos,
                     resultados=len(fluxo.apurador.resultados),
                     pendente=fluxo.apurador.pendente is not None, **fluxo.metricas)
    print(json.dumps(relatorio, ensure_ascii=False))
    if fluxo.metricas["ticks_aceitos"] < 10 or (exigir_m1 and (fechados < 22 or leituras < 1)):
        raise RuntimeError("Teste inconclusivo: faltaram 22 velas contíguas recentes e leitura de indicadores")
    if telegram and (not fluxo.apurador.resultados or fluxo.metricas['telegram_confirmados'] < 2
                     or fluxo.metricas['telegram_falhas']):
        raise RuntimeError("Telegram inconclusivo: ciclo de sinal e resultado não confirmado sem falhas")
    print("Streaming validado nesta janela; nenhuma operação enviada.")
    return relatorio


def main():
    try:
        executar()
    except (RuntimeError, ValueError) as erro:
        print(str(erro))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
