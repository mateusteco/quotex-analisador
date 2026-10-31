"""
Teste de streaming da OTCharts para Quotex.
Nao executa operacoes financeiras.
"""

import os
import json
import time
import requests

API_KEY = os.getenv("OTCHARTS_API_KEY")
SYMBOL = "BRLUSD_otc"
URL = "https://otcharts.com/v1/stream"

def main():
    if not API_KEY:
        raise RuntimeError(
            "OTCHARTS_API_KEY nao configurada."
        )

    print("NEXUS OTC ANALYZER")
    print("Testando streaming da Quotex...")
    print("Instrumento:", SYMBOL)

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "text/event-stream"
    }

    params = {
        "venue": "quotex",
        "symbol": SYMBOL
    }

    inicio = time.monotonic()
    recebidos = 0
    conectado = False
    evento = None

    with requests.get(
        URL,
        headers=headers,
        params=params,
        stream=True,
        timeout=(10, 10)
    ) as resposta:

        resposta.raise_for_status()

        for linha in resposta.iter_lines(
            chunk_size=1,
            decode_unicode=True
        ):
            if time.monotonic() - inicio >= 20:
                break

            if not linha:
                continue

            if linha.startswith("event:"):
                evento = linha[6:].strip()
                continue

            if not linha.startswith("data:"):
                continue

            dados = json.loads(linha[5:].strip())

            if evento == "connected":
                conectado = True
                print("Conexao estabelecida.")
                print("Instrumentos:", dados.get("symbols"))

            elif evento == "tick":
                if dados.get("symbol") == SYMBOL:
                    recebidos += 1
                    print(
                        "Tick:",
                        dados.get("time"),
                        "Preco:",
                        dados.get("price")
                    )

            elif evento in ("dropped", "closed", "replaced"):
                print("Evento:", evento, dados)

            evento = None

            if recebidos >= 10:
                break

    print("Total de ticks recebidos:", recebidos)

    if not conectado:
        print("Conexao nao confirmada.")

    if recebidos == 0:
        print("Nenhum preco recebido no teste.")
    else:
        print("Streaming funcionando!")

if __name__ == "__main__":
    main()
