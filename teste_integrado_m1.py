"""Teste integrado de ticks OTCharts e agregacao M1, sem ordens."""
import json
import os
import time
import requests
from stream_m1 import M1Builder
from fluxo_alertas_m1 import FluxoM1

def main():
    key = os.environ["OTCHARTS_API_KEY"]
    fluxo = FluxoM1(enviar_telegram=os.getenv('ENVIAR_TELEGRAM_SIMULACAO') == '1')
    ticks = 0
    fechados = 0
    leituras = 0
    inicio = time.monotonic()
    modo_telegram = os.getenv('ENVIAR_TELEGRAM_SIMULACAO') == '1'
    resultados_iniciais = 0
    with requests.get(
        "https://otcharts.com/v1/stream",
        headers={"Authorization": f"Bearer {key}", "Accept": "text/event-stream"},
        params={"venue": "quotex", "symbol": "BRLUSD_otc"},
        stream=True, timeout=(10, 20)
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines(chunk_size=1, decode_unicode=True):
            if time.monotonic() - inicio > 1800:
                break
            if not line or not line.startswith("data:"):
                continue
            data = json.loads(line[5:].strip())
            if data.get("symbol") != "BRLUSD_otc" or "price" not in data:
                continue
            ts = data.get("time")
            if ts is None:
                continue
            antes = fluxo.builder.atual.inicio if fluxo.builder.atual else None
            mensagem = fluxo.tick(ts, data["price"])
            ticks += 1
            depois = fluxo.builder.atual.inicio if fluxo.builder.atual else None
            if antes is not None and depois is not None and depois > antes:
                fechados += 1
                if fluxo.indicadores.ultimo_inicio == antes:
                    leituras += 1
            if mensagem:
                print("Alerta teorico preparado:", mensagem)
            if len(fluxo.apurador.resultados) > resultados_iniciais:
                resultados_iniciais = len(fluxo.apurador.resultados)
                print("Resultado simulado apurado:", fluxo.apurador.resultados[-1]["resultado"])
            if modo_telegram:
                # Neste modo, so encerrar apos sinal + vela seguinte apurada,
                # ou pelo limite de 30 minutos. Pode nao surgir sinal.
                if resultados_iniciais >= 1 and fechados >= 22:
                    break
            elif fechados >= 22 and ticks >= 10:
                break
    print(f"Ticks: {ticks}; candles M1 fechados: {fechados}; leituras completas: {leituras}")
    print("Observacao: indicadores precisam de 22 velas fechadas para aquecimento.")
    if ticks < 10 or fechados < 22 or leituras < 1:
        raise RuntimeError("Teste inconclusivo: faltaram ticks, 22 velas ou leitura de indicadores")
    if modo_telegram:
        print(f"Resultados simulados apurados: {len(fluxo.apurador.resultados)}")
        if not fluxo.apurador.resultados:
            print("Sem ciclo completo de sinal e resultado nesta janela; nenhum resultado inventado.")
    print("Streaming integrado ao M1: OK; nenhuma operacao enviada")

if __name__ == "__main__":
    main()
