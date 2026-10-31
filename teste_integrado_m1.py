"""Teste integrado de ticks OTCharts e agregacao M1, sem ordens."""
import json
import os
import time
import requests
from stream_m1 import M1Builder

def main():
    key = os.environ["OTCHARTS_API_KEY"]
    builder = M1Builder()
    ticks = 0
    fechados = 0
    inicio = time.monotonic()
    with requests.get(
        "https://otcharts.com/v1/stream",
        headers={"Authorization": f"Bearer {key}", "Accept": "text/event-stream"},
        params={"venue": "quotex", "symbol": "BRLUSD_otc"},
        stream=True, timeout=(10, 20)
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines(chunk_size=1, decode_unicode=True):
            if time.monotonic() - inicio > 100:
                break
            if not line or not line.startswith("data:"):
                continue
            data = json.loads(line[5:].strip())
            if data.get("symbol") != "BRLUSD_otc" or "price" not in data:
                continue
            ts = data.get("time")
            if ts is None:
                continue
            candle = builder.adicionar(ts, data["price"])
            ticks += 1
            if candle:
                fechados += 1
                print("M1 fechado:", candle)
            if fechados >= 1 and ticks >= 10:
                break
    print(f"Ticks: {ticks}; candles M1 fechados: {fechados}")
    if ticks < 10 or fechados < 1:
        raise RuntimeError("Teste inconclusivo: faltaram ticks ou virada de minuto")
    print("Streaming integrado ao M1: OK; nenhuma operacao enviada")

if __name__ == "__main__":
    main()
