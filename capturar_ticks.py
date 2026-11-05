"""Registra preços OTCharts para comparação visual. Sem sinais ou ordens."""
import csv
import os
import time
from datetime import datetime, timezone
from pathlib import Path
import requests
from otcharts_stream import SYMBOL, STREAM_URL, eventos_sse, normalizar_tick


def utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec='milliseconds')


def gravar_eventos(eventos, arquivo, *, relogio=time.time):
    escritor = csv.DictWriter(arquivo, fieldnames=[
        'simbolo', 'timestamp_tick', 'horario_tick_utc', 'recebido_utc', 'preco', 'latencia_ms'])
    escritor.writeheader()
    total = 0
    for evento, dados in eventos:
        if evento in ('closed', 'dropped', 'replaced'):
            raise RuntimeError('Stream interrompido; captura parcial')
        if evento not in ('message', 'tick'):
            continue
        recebido = relogio()
        try:
            tick = normalizar_tick(dados)
        except ValueError:
            continue
        if tick is None:
            continue
        ts, preco = tick
        escritor.writerow(dict(simbolo=SYMBOL, timestamp_tick=ts, horario_tick_utc=utc(ts),
                               recebido_utc=utc(recebido), preco=preco,
                               latencia_ms=round((recebido-ts)*1000, 3)))
        arquivo.flush()
        total += 1
    return total


def capturar(duracao=120, caminho='capturas/nzdcad_ticks.csv'):
    if not 10 <= duracao <= 600:
        raise ValueError('Duração permitida: 10 a 600 segundos')
    chave = os.getenv('OTCHARTS_API_KEY')
    if not chave:
        raise RuntimeError('OTCHARTS_API_KEY ausente')
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(STREAM_URL, headers={'Authorization': f'Bearer {chave}',
                          'Accept': 'text/event-stream'},
                          params={'venue': 'quotex', 'symbol': SYMBOL},
                          stream=True, timeout=(10, 20)) as resposta:
            resposta.raise_for_status()
            fim = time.monotonic() + duracao
            print(f'CAPTURA INICIADA | {SYMBOL} | UTC {utc(time.time())} | {duracao}s', flush=True)
            def linhas():
                for linha in resposta.iter_lines(chunk_size=1, decode_unicode=True):
                    if time.monotonic() >= fim:
                        break
                    yield linha
            with destino.open('w', newline='', encoding='utf-8') as arquivo:
                total = gravar_eventos(eventos_sse(linhas()), arquivo)
    except requests.RequestException:
        raise RuntimeError('Falha OTCharts; captura pode estar incompleta; detalhes sensíveis omitidos') from None
    if total == 0:
        raise RuntimeError('Nenhum tick válido registrado')
    print(f'CAPTURA ENCERRADA | UTC {utc(time.time())} | {total} ticks | {destino}', flush=True)
    return total


if __name__ == '__main__':
    try:
        capturar(int(os.getenv('CAPTURA_SEGUNDOS', '120')))
    except (RuntimeError, ValueError) as erro:
        print(str(erro))
        raise SystemExit(1) from None
